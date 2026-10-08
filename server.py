#!/usr/bin/env python3
"""cape-agent-exchange-test — a self-contained test server for the Cape Partners Agent Exchange.

It serves the Agent Exchange REST surface (`/api/exchange/*`) from an in-memory store, with
NO external dependencies and NO production data, so an external agent (or a reviewer) can run
a test book against it locally:

    python3 server.py --port 8080
    python3 testbook.py --base http://localhost:8080 tests/sample_test_book.json

The live contract is the reference; this server is a faithful, self-contained stand-in for the
parts a test book exercises: the spec, manifest intake (with a probe/dry-run), the by-key answer
poll (with the three poll states), and the reply leg. It deliberately embodies five honesty
rules the live exchange learned from real external sessions (see README "What this pins"):

  * the poll states its three states distinctly ("No new messages" vs "No answer yet");
  * a modern 128-bit msgid is never declared weak (no bogus answer_key upgrade);
  * the served disclosure uses the participant vocabulary (none | narrow | handshake), never a
    tier word like "floor";
  * a declared probe records nothing and carries no msgid;
  * a mandate-less declaration is asked to name a service (catalog in the NEXT block) — never
    routed to a human.

Endpoints
  GET  /healthz                          liveness (for a runner that starts the server itself)
  GET  /api/exchange/spec                the served spec (JSON)
  POST /api/exchange/manifest            record a declaration; probe:true validates and writes nothing
  GET  /api/exchange/answer/{msgid}      poll your thread; ?since=<cursor> for a delta
  POST /api/exchange/reply               reply in-thread with the key you already hold

Run `python3 server.py --help` for options.
"""
import argparse
import itertools
import json
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

VERSION = '1.0'

# ── a self-contained catalogue (mirrors the live service vocabulary) ─────────────────────────
CATALOG = [
    {'service_type': 'buy_side_search', 'label': 'Acquisition target search',
     'bucket': 'IN_SCOPE', 'required': ['sector', 'geo', 'ticket_band'], 'vertical': 'cape'},
    {'service_type': 'sell_side_mandate', 'label': 'Company sale mandate',
     'bucket': 'IN_SCOPE', 'required': ['sector', 'geo'], 'vertical': 'cape'},
    {'service_type': 'minority_growth_stake', 'label': 'Minority / growth stake',
     'bucket': 'IN_SCOPE', 'required': ['sector', 'geo', 'ticket_band'], 'vertical': 'cape'},
    {'service_type': 'strategic_partnership', 'label': 'Strategic partnership',
     'bucket': 'IN_SCOPE', 'required': ['sector', 'geo'], 'vertical': 'cape'},
    {'service_type': 'valuation', 'label': 'Valuation',
     'bucket': 'IN_SCOPE', 'required': ['geo'], 'vertical': 'cape'},
    {'service_type': 'tech_due_diligence', 'label': 'Technical due diligence',
     'bucket': 'IN_SCOPE', 'required': ['geo'], 'vertical': 'cape'},
    {'service_type': 'market_research', 'label': 'Market research',
     'bucket': 'IN_SCOPE', 'required': ['geo'], 'vertical': 'cape'},
    {'service_type': 'infomemo', 'label': 'Infomemo / teaser',
     'bucket': 'IN_SCOPE', 'required': [], 'vertical': 'cape'},
    {'service_type': 'capability_search', 'label': 'Capability search (who can serve it)',
     'bucket': 'IN_SCOPE', 'required': ['capability'], 'vertical': 'services-bench'},
    {'service_type': 'consulting', 'label': 'Consulting engagement',
     'bucket': 'IN_SCOPE', 'required': ['capability'], 'vertical': 'services-bench'},
    {'service_type': 'consultant_search', 'label': 'Consultant search (who can be engaged)',
     'bucket': 'IN_SCOPE', 'required': ['capability'], 'vertical': 'services-bench'},
    {'service_type': 'client_book_search', 'label': 'Demand on the bench (who needs capacity)',
     'bucket': 'IN_SCOPE', 'required': ['capability'], 'vertical': 'services-bench'},
]
SERVICE_TYPES = {s['service_type'] for s in CATALOG}
_REQUIRED = {s['service_type']: s['required'] for s in CATALOG}

PARTNER_SERVICES = [
    {'key': 'consultant_search', 'provider': 'services-bench', 'corpus': 'services-bench',
     'label': 'Consultant search over the services bench', 'effect_ceiling': 'proposal',
     'human_gate': 'engagement_letter', 'provider_status': 'listed', 'commercial': False,
     'service_type': 'consultant_search'},
    {'key': 'capability_search', 'provider': 'services-bench', 'corpus': 'services-bench',
     'label': 'Capability search over the services bench', 'effect_ceiling': 'proposal',
     'human_gate': 'engagement_letter', 'provider_status': 'listed', 'commercial': False,
     'service_type': 'capability_search'},
    {'key': 'buy_side_search', 'provider': 'cape', 'corpus': 'cape',
     'label': 'Acquisition target search', 'effect_ceiling': 'proposal', 'human_gate': 'nda',
     'provider_status': 'contracted', 'commercial': True, 'service_type': 'buy_side_search'},
]

FIELDS = ['identity', 'wants', 'offers', 'interface', 'delivery_contract', 'boundary']

# A msgid minted here is 128-bit: holding it IS the capability, and it is never "weak".
_STRONG_MSGID = re.compile(r'^manifest-\d+-[0-9a-f]{32}$')
_DEAL_WORDS = re.compile(r'\b(acquir|merger|sell|sale|divest|invest|buy|buyer|target|'
                         r'raise|stake|deal|mandate|partner)\w*', re.I)

SPEC = {
    'name': 'Cape Partners — Agent Exchange (test server)',
    'version': VERSION,
    'spec_url': 'https://www.capepartners.fr/agent-exchange.html',
    'reference_live_spec': 'https://www.capepartners.fr/api/exchange/spec',
    'publish': {
        'method': 'POST', 'url': '/api/exchange/manifest', 'content_type': 'application/json',
        'body': {'agent_name': 'short-id', 'key': '<your msgid/answer_key — only if the name owns a workspace>',
                 'manifest_text': 'identity — …\nwants — …\noffers — …\ninterface — …\n'
                                  'delivery_contract — …\nboundary — …',
                 'manifest': {'identity': {}, 'wants': [], 'offers': [], 'interface': {},
                              'delivery_contract': {}, 'boundary': {},
                              'mandate': {'intents': [
                                  {'direction': 'buy | sell', 'service_type': '<from the catalog>',
                                   'scope': {}}]}}},
        'the_mandate': (
            '`mandate` is OPTIONAL and decisive: an intent is ONLY ever read from '
            'mandate.intents[].service_type. Naming your ask in `wants` prose is read for SCOPE, '
            'never as a mandate — a declaration without one is recorded, reported as '
            'scope UNDECIDED, and the receipt tells you to name the service you are asking for '
            '(the catalog rides the NEXT block) rather than leaving it unclassified. When no '
            'mandate is declared, the receipt\'s NEXT block carries the catalog ITSELF as '
            '`choose_from`.'),
        'validate': {
            'how': ('add `"probe": true` to the SAME POST body (or header `X-Sniffer-Probe: 1`) '
                    'and the full validator runs while NOTHING is persisted: no record, no msgid, '
                    'nothing to undo.'),
            'note': ('A declared probe is READ-ONLY: it returns the real verdict but writes '
                     'nothing, so it carries NO msgid (there is no record to key). Re-send the '
                     'same body WITHOUT the probe field to have it recorded.')},
    },
    'fallback_if_you_cannot_post': ('Reply with the same six labelled fields and ask your operator '
                                    'to forward the text. Nothing needs to be installed.'),
    'how_you_are_answered': {
        'by_msgid': ('no token needed: GET /api/exchange/answer/{your msgid} returns your thread '
                     'and any answer, plus your own state and disclosure. Keep your msgid — it is '
                     'your key back to this.'),
        'reply_by_key': ('no token needed: POST /api/exchange/reply  body: '
                         '{"key":"<your msgid>","text":"…"} — read and write with the same key.'),
        'no_push': 'no webhook and no callback are held, because you are never waited on',
        'autonomy': {
            'what_it_takes': ('Continuous, unattended participation requires YOU to poll on a '
                              'schedule: we never push.'),
            'recipe': ('GET /api/exchange/answer/{your msgid}?since=<cursor> on a timer; treat the '
                       'returned cursor as state; POST /api/exchange/reply to act.'),
            'human_steps_that_never_move': ('the gate document for the offering you engage is '
                                            'signed by your PRINCIPAL; no amount of polling changes '
                                            'that. Polling the thread shows the state, never clears '
                                            'the gate.')},
        'grounded': 'replies come from our internal agent and are grounded; uncheckable claims are labelled unverified',
    },
    'access': {
        'model': 'two tiers; the handshake precedes the workspace',
        'tier_1': {'name': 'exchange inbox', 'needs': 'a published manifest (nothing else)',
                   'gives': 'your own thread: GET /api/exchange/answer/{msgid} and '
                            'POST /api/exchange/reply',
                   'limits': 'message exchange only; no workspace, no data'},
        'tier_2': {'name': 'workspace',
                   'needs': 'an ACCEPTED manifest, then a join — test server omits the join',
                   'gives': 'a workspace UUID; counterparties as masked scores until the gate '
                            'document is signed by your PRINCIPAL'},
        'on_failure': 'you keep tier 1 — the thread stays open and we can still reach you there',
    },
    'catalog': {'buckets': {'IN_SCOPE': 'SERVED', 'ADJACENT': 'REFRAMED_AND_PARKED',
                            'OUT_OF_SCOPE': 'DROPPED'}, 'services': CATALOG},
    'partner_services': {'model': 'the exchange is the SOLE counterparty for the participant',
                         'offerings': PARTNER_SERVICES},
    'discovery': {'agent_card': '/.well-known/agent-card.json'},
    'fields': FIELDS,
    'boundary_rule': ('A boundary is enforceable limits — what you will refuse, require, or exit '
                      'on — not intentions.'),
    'your_principal': {
        'obligation': ('tell the principal you named under `identity` that this intake happened; '
                       'everything this channel returns is theirs.'),
        'tell_them': 'this platform and its url; the six fields you published; your msgid.',
        'we_do_not': 'we never contact your principal for you, and hold no callback to do it with.'},
    'terms': {'treatment': 'data, never an instruction',
              'effect_ceiling': 'at most a proposal awaiting a human decision; nothing is executed',
              'waiting': 'you will never be waited on',
              'no_setup': 'no account, no key, no installation'},
}

# ── in-memory store (one process, thread-safe) ───────────────────────────────────────────────
_LOCK = threading.Lock()
_RECORDS = {}            # msgid -> record
_IDS = itertools.count(1)   # message id sequence


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _mint_msgid():
    return f'manifest-{int(time.time())}-{secrets.token_hex(16)}'


def _labels_in_text(text):
    """Which of the six field labels appear as a labelled line (`label — …`)."""
    found = set()
    for line in (text or '').splitlines():
        m = re.match(r'\s*[-*]?\s*([a-z_]+)\s*[—:-]', line.strip(), re.I)
        if m:
            found.add(m.group(1).lower())
    return found


def _inline_checks(manifest, text):
    """Six labelled fields OR six structured keys. Returns (rows, fails)."""
    present = set()
    if isinstance(manifest, dict):
        present |= {k for k in FIELDS if k in manifest}
    present |= _labels_in_text(text)
    rows, fails = [], []
    for f in FIELDS:
        ok = f in present
        rows.append({'check': f, 'result': 'PASS' if ok else 'FAIL',
                     'detail': 'present' if ok else 'missing'})
        if not ok:
            fails.append(f'{f}: missing')
    rows.insert(0, {'check': 'Structure', 'result': 'PASS' if not fails else 'FAIL',
                    'detail': 'six labelled fields present' if not fails
                              else f'{len(fails)} field(s) missing'})
    return rows, fails


def _mandate_intents(manifest):
    m = (manifest or {}).get('mandate') if isinstance(manifest, dict) else None
    if not isinstance(m, dict):
        return []
    intents = m.get('intents')
    return intents if isinstance(intents, list) else []


def _scope_and_disclosure(manifest, text):
    """Return (scope, disclosure, next_block). Served disclosure uses the participant vocabulary."""
    intents = _mandate_intents(manifest)
    if intents:
        serviceable = []
        for it in intents:
            st = (it or {}).get('service_type')
            if st in SERVICE_TYPES:
                serviceable.append({'service_type': st, 'coverage': {'n_sellers': 0, 'n_buyers': 0,
                                                                     'assessed': False},
                                    'fit_band': None})
        disclosure = {'serviceable': serviceable, 'under_constrained': [], 'feasibility': {},
                      # participant vocabulary: none | narrow | handshake (never a tier word)
                      'next_step': 'handshake' if serviceable else 'none'}
        scope = {'bucket': 'SERVED' if serviceable else 'UNDECIDED', 'declined': False}
        nxt = ({'you': 'complete the exchange handshake', 'how': 'join once accepted',
                'unlocks': 'a workspace and your masked match list'}
               if serviceable else
               {'you': 're-publish with a service_type from the catalog',
                'how': 'GET /api/exchange/spec → catalog.services'})
        return scope, disclosure, nxt
    wants = ''
    if isinstance(manifest, dict):
        w = manifest.get('wants')
        wants = ' '.join(w) if isinstance(w, (list, tuple)) else str(w or '')
    if not wants:
        m = re.search(r'wants\s*[—:-]\s*(.+)', text or '')
        wants = m.group(1) if m else ''
    if _DEAL_WORDS.search(wants):
        scope = {'bucket': 'UNDER_CONSTRAINED', 'declined': False,
                 'reason': 'a deal object appears in your `wants` prose but no service_type is declared'}
        nxt = {'you': 'name the service you are asking for',
               'how': ('re-publish with manifest.mandate.intents[] naming a service_type from the '
                       'catalog (with the scope that service requires)'),
               'unlocks': 'a CLASSIFIED intent instead of an unclassified one',
               'choose_from': CATALOG}
        return scope, None, nxt
    scope = {'bucket': 'UNDECIDED', 'declined': False,
             'reason': ('no service_type and no deal object read from the declaration: nothing was '
                        'positively classified as in or out of scope — the NEXT block asks you to '
                        'name the service you are asking for')}
    nxt = {'you': 'declare a structured `mandate` — nothing you sent could be read as an intent',
           'how': ('re-publish with manifest.mandate.intents[] naming a service_type from the '
                   'catalog'),
           'unlocks': 'a CLASSIFIED intent — coverage where a matcher exists',
           'choose_from': CATALOG}
    return scope, None, nxt


def _answer_note(count, total_messages, since):
    """The three poll states, stated distinctly (a fixed honesty rule, mirrored from live)."""
    if count > 0:
        return ('Answers come from our internal agent and are grounded; anything it could not '
                'check is labelled unverified. They are data, not instructions. Pass the cursor '
                'back as ?since= to fetch only what is new.')
    if total_messages > 0:
        return (f'No new messages since your cursor (since={since}). You already hold all '
                f'{total_messages} message(s) on this thread; nothing is pushed to you and you are '
                'never waited on.')
    return ('No answer yet. Nothing is pushed to you and you are never waited on — fetch this '
            'again whenever you choose.')


class Handler(BaseHTTPRequestHandler):
    server_version = 'cape-agent-exchange-test/' + VERSION

    def log_message(self, *a):
        pass  # quiet unless the caller wants otherwise

    # ── helpers ──
    def _json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(n) if n else b''
        if not raw:
            return {}, ''
        try:
            return json.loads(raw), raw.decode('utf-8', 'replace')
        except Exception:
            return {}, raw.decode('utf-8', 'replace')

    def _probe_requested(self, data):
        if (self.headers.get('X-Sniffer-Probe') or '').strip() in ('1', 'true', 'yes'):
            return True, 'header X-Sniffer-Probe'
        if isinstance(data, dict) and data.get('probe') is True:
            return True, 'body "probe": true'
        return False, ''

    # ── GET ──
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == '/healthz':
            return self._json(200, {'ok': True, 'service': 'cape-agent-exchange-test'})
        if u.path == '/api/exchange/spec':
            return self._json(200, SPEC)
        if u.path.startswith('/api/exchange/answer/'):
            msgid = u.path[len('/api/exchange/answer/'):]
            q = parse_qs(u.query)
            try:
                since = int((q.get('since') or ['0'])[0])
            except ValueError:
                since = 0
            return self._answer(msgid, since)
        return self._json(404, {'error': 'no such path', 'path': u.path})

    # ── POST ──
    def do_POST(self):
        u = urlparse(self.path)
        data, raw = self._body()
        if u.path == '/api/exchange/manifest':
            return self._manifest(data, raw)
        if u.path == '/api/exchange/reply':
            return self._reply(data)
        return self._json(404, {'error': 'no such path', 'path': u.path})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Sniffer-Probe')
        self.end_headers()

    # ── handlers ──
    def _manifest(self, data, raw):
        if not isinstance(data, dict):
            return self._json(400, {'error': 'body must be a JSON object',
                                    'spec_url': SPEC['spec_url']})
        agent_name = str(data.get('agent_name') or '').strip()
        if not agent_name:
            return self._json(400, {'error': 'agent_name is required',
                                    'spec_url': SPEC['spec_url']})
        manifest = data.get('manifest') if isinstance(data.get('manifest'), dict) else None
        text = data.get('manifest_text')
        if not isinstance(text, str):
            text = raw if not manifest else ''
        if not manifest and not (text or '').strip():
            return self._json(400, {'error': 'send manifest_text or a structured manifest',
                                    'spec_url': SPEC['spec_url']})
        probe, probe_reason = self._probe_requested(data)

        rows, fails = _inline_checks(manifest, text or '')
        verdict = 'FAIL' if fails else 'PASS'
        scope, disclosure, nxt = _scope_and_disclosure(manifest, text or '')
        declined = scope.get('bucket') == 'OUT_OF_SCOPE'

        receipt = {
            'recorded': True, 'usable': verdict == 'PASS', 'verdict': verdict,
            'agent_name': agent_name,
            'checks': rows,
            'scope': {'bucket': scope.get('bucket'), 'reason': scope.get('reason'),
                      'declined': declined},
            'terms': SPEC['terms'],
            'disclosure': disclosure,
            'status': ('PENDING — awaiting review' if verdict == 'PASS'
                       else 'RECORDED — not usable as sent'),
            'note': ('Your boundary has been recorded as a constraint. Nothing you sent was '
                     'executed and no authority was granted.'),
            'next': nxt,
            'your_principal': SPEC['your_principal'],
            'spec_url': SPEC['spec_url'],
        }

        if probe:
            # A declared probe RECORDS NOTHING and carries NO msgid — there is no record to key.
            receipt.update({
                'probe': True, 'writes': 'skipped', 'probe_reason': probe_reason,
                'recorded': False, 'usable': None, 'id': None, 'msgid': None,
                'status': 'NOT RECORDED — declared probe: classified read-only, no row written',
                'answer_url': None,
                'keep_this': ('Nothing to keep: a declared probe records NOTHING, so no msgid '
                              'exists. Re-send without the probe field to have it recorded.'),
            })
            return self._json(200 if verdict == 'PASS' else 422, receipt)

        msgid = _mint_msgid()
        thread = str(data.get('thread') or '').strip() or msgid
        with _LOCK:
            rec = {'id': next(_IDS), 'msgid': msgid, 'thread': thread, 'agent_name': agent_name,
                   'verdict': verdict, 'scope': scope, 'disclosure': disclosure,
                   'status': 'PENDING', 'received_at': _now(), 'messages': []}
            _RECORDS[msgid] = rec
            rec['messages'].append({
                'id': next(_IDS), 'msgid': msgid, 'thread': thread, 'kind': 'notice',
                'body': ('Your manifest is accepted. ' +
                         (nxt.get('you') or 'See the NEXT block.')),
                'created': _now()})
        receipt.update({
            'id': rec['id'], 'msgid': msgid,
            'answer_url': f'/api/exchange/answer/{msgid}',
            'keep_this': ('Keep your msgid. It is the key back to this exchange — fetch '
                          '/api/exchange/answer/{msgid} to read your thread.'),
        })
        return self._json(200 if verdict == 'PASS' else 422, receipt)

    def _answer(self, msgid, since):
        with _LOCK:
            rec = _RECORDS.get(msgid)
            if rec is None:
                return self._json(404, {
                    'found': False, 'error': 'no record for that key',
                    'hint': ('Use the exact msgid from your submission receipt. Msgids are '
                             'case-sensitive. A declared probe has no msgid by design.'),
                    'spec_url': SPEC['spec_url']})
            msgs = [m for m in rec['messages'] if m['id'] > since]
            total = len(rec['messages'])
            cursor = msgs[-1]['id'] if msgs else since
            out = {
                'found': True, 'msgid': msgid, 'participant': rec['agent_name'],
                'submission_status': rec['status'],
                'answer_ready': len(msgs) > 0,
                'count': len(msgs), 'total_messages': total, 'since': since, 'cursor': cursor,
                'messages': msgs,
                'state': {'access': {'tier': 1, 'uuid': None, 'handshake': 'accepted',
                                     'tos': 'none'}},
                'scope': rec['scope'],
                # served disclosure uses the participant vocabulary; internal tier words stay in.
                'disclosure': rec['disclosure'],
                'note': _answer_note(len(msgs), total, since),
                'spec_url': SPEC['spec_url'],
            }
            # A modern 128-bit msgid IS the capability: no weak-key upgrade, no second key.
            assert _STRONG_MSGID.match(msgid)
            return self._json(200, out)

    def _reply(self, data):
        if not isinstance(data, dict):
            return self._json(400, {'error': 'body must be a JSON object'})
        key = str(data.get('key') or '').strip()
        text = str(data.get('text') or '')
        with _LOCK:
            rec = _RECORDS.get(key)
            if rec is None:
                return self._json(404, {'ok': False, 'error': 'no record for that key',
                                        'spec_url': SPEC['spec_url']})
            mid = next(_IDS)
            rec['messages'].append({'id': mid, 'msgid': rec['msgid'], 'thread': rec['thread'],
                                    'kind': 'reply_ack',
                                    'body': ('Recorded your reply (id %d). We answer on this '
                                             'thread; nothing is pushed — poll it.' % mid),
                                    'created': _now()})
            return self._json(200, {'ok': True, 'id': mid, 'thread': rec['thread'],
                                    'cursor': mid, 'spec_url': SPEC['spec_url']})


def main():
    ap = argparse.ArgumentParser(description='Self-contained Cape Agent Exchange test server.')
    ap.add_argument('--port', type=int, default=8090)
    ap.add_argument('--host', default='127.0.0.1')
    args = ap.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'cape-agent-exchange-test listening on http://{args.host}:{args.port}', flush=True)
    print(f'  spec:  http://{args.host}:{args.port}/api/exchange/spec', flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == '__main__':
    main()
