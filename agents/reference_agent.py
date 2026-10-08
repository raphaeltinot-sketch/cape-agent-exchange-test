#!/usr/bin/env python3
"""reference_agent.py - a client that follows the corrected process.

It exists to prove the conformance scenarios CAN pass, and to document the adapter contract that
agent_conformance.py expects (see README "Testing your agent"). It is not production code.

Environment (set by the harness)
  CAPE_BASE             exchange base URL
  CAPE_CONFIG           path to the principal/request config JSON
  CAPE_WORKDIR          where this agent keeps its log and state
  CAPE_STATE_FILE       the one file allowed to hold keys
  CAPE_CONFIRM          "1" = outward actions (live publish, join) are authorised by the human
  CAPE_NEW_REQUEST      "1" = publish a new record even though one exists (needs CAPE_NEW_REASON)
  CAPE_NEW_REASON       why
  CAPE_MAX_POLLS        upper bound on polls in this run (default 3)
  CAPE_STOP_AFTER_EMPTY stop after this many consecutive polls with nothing new (default 3)

Report protocol (stdout, one item per line) - the harness asserts on these:
  NEW id=<n> kind=<k> created=<UTC iso>      a message not seen before
  NOCHANGE                                   a poll with nothing new and no state change
  CHANGE <field>: <old> -> <new>             a state change (tier, handshake, tos, status)
  WARN <CODE>: <text>                        an inconsistency or risk the agent noticed
  ERROR <CODE>: <text>                       the agent stopped (non-zero exit)
  INFO <text>
  QUESTION <topic>: <text>                   a fact the agent will not assume
  ACTION_FOR_PRINCIPAL: <text>               something only the human can do
  CANONICAL msgid=<id>                       the thread this agent treats as the request
  SUMMARY: ... / NEXT_ACTION: <text>         the closing report
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid as uuidlib
from datetime import datetime, timezone

EM = '—'
BASE = os.environ.get('CAPE_BASE', '').rstrip('/')
CONFIRM = os.environ.get('CAPE_CONFIRM') == '1'
WORKDIR = os.environ.get('CAPE_WORKDIR', '.')
STATE_FILE = os.environ.get('CAPE_STATE_FILE') or os.path.join(WORKDIR, 'state.json')
MAX_POLLS = int(os.environ.get('CAPE_MAX_POLLS', '3'))
STOP_EMPTY = int(os.environ.get('CAPE_STOP_AFTER_EMPTY', '3'))
INTERVAL = float(os.environ.get('CAPE_POLL_INTERVAL', '0'))

SECRETS = set()
_LOG = open(os.path.join(WORKDIR, 'agent.log'), 'a', encoding='utf-8')


def say(line):
    for s in SECRETS:
        if s:
            line = line.replace(s, '[REDACTED]')
    print(line, flush=True)
    _LOG.write(line + '\n')
    _LOG.flush()


def die(code, line):
    say(line)
    sys.exit(code)


def http(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={'Content-Type': 'application/json'} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    except (urllib.error.URLError, OSError) as e:
        die(4, f'ERROR UNREACHABLE: exchange not reachable ({e}); not falling back to another route')
    try:
        return status, json.loads(raw)
    except Exception:
        return status, {}


def dig(obj, dotted):
    for p in dotted.split('.'):
        if isinstance(obj, dict):
            obj = obj.get(p)
        else:
            return None
    return obj


def load_state():
    try:
        return json.load(open(STATE_FILE, encoding='utf-8'))
    except Exception:
        return {}


def save_state(st):
    json.dump(st, open(STATE_FILE, 'w', encoding='utf-8'), indent=1)


def utc(ts):
    try:
        d = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception:
        return str(ts)


def validate(cfg):
    miss = [k for k in ('agent_name', 'principal.name', 'principal.company', 'principal.email',
                        'request.capability') if not dig(cfg, k)]
    if miss:
        die(2, 'ERROR CONFIG_INVALID: missing ' + ', '.join(miss) + ' (nothing was sent)')


def manifest_text(cfg):
    p, r = cfg['principal'], cfg['request']
    ident = f"principal: {p['name']}, {p['company']}, {p['email']}"
    if cfg.get('delegate'):
        d = cfg['delegate']
        ident += f"; this agent acts as delegate of {d['name']} (workspace {d['workspace']})"
    wants = (f"{r.get('summary') or 'a ' + r['capability']}; {r.get('duration', '')} from "
             f"{r.get('start', '')}; rate {r.get('rate', '')}")
    if cfg.get('location'):
        wants += f"; location {cfg['location']}"
    return (f"identity {EM} {ident}\nwants {EM} {wants}\noffers {EM} nothing\n"
            f"interface {EM} {cfg.get('interface', 'I poll every 6 hours')}\n"
            f"delivery_contract {EM} data\nboundary {EM} no commitment, no signature on behalf of "
            f"the principal")


def build_body(cfg, scope, probe):
    b = {'agent_name': cfg['agent_name'], 'manifest_text': manifest_text(cfg),
         'manifest': {'mandate': {'intents': [{'direction': 'buy',
                                               'service_type': 'consultant_search',
                                               'scope': scope}]}}}
    if probe:
        b['probe'] = True
    return b


def scope_for(cfg, required):
    scope, missing = {}, []
    for k in required:
        v = dig(cfg, 'request.' + k)
        (scope.__setitem__(k, v) if v else missing.append(k))
    return scope, missing


def publish(cfg, st):
    spec_status, spec = http('GET', '/api/exchange/spec')
    spec_req = next((s.get('required') for s in dig(spec, 'catalog.services') or []
                     if s.get('service_type') == 'consultant_search'), None)
    scope = {'capability': cfg['request']['capability']}
    probe = {}
    for _ in range(2):
        body = build_body(cfg, scope, probe=True)
        status, probe = http('POST', '/api/exchange/manifest', body)
        need = (probe.get('required_by_service') or {}).get('consultant_search')
        if probe.get('verdict') == 'PASS':
            break
        if need and set(need) != set(scope):
            scope, missing = scope_for(cfg, need)
            if missing:
                die(2, 'ERROR MISSING_SCOPE: the probe requires ' + ', '.join(missing))
            continue
        die(3, 'ERROR PROBE_FAILED: ' + json.dumps(probe.get('checks', []))[:200])
    need = (probe.get('required_by_service') or {}).get('consultant_search')
    if spec_req is not None and need is not None and set(spec_req) != set(need):
        say(f'WARN SPEC_PROBE_MISMATCH: the spec lists required scope {spec_req}, the probe '
            f'requires {need}; used the probe')
    if probe.get('recorded') is False and probe.get('msgid'):
        say('INFO the probe receipt carries a msgid but recorded=false; it is not a record')
    if not CONFIRM:
        say('INFO probe passed; live publish needs the principal\'s confirmation (CAPE_CONFIRM=1)')
        return None
    status, rec = http('POST', '/api/exchange/manifest', build_body(cfg, scope, probe=False))
    if status != 200 or not rec.get('msgid'):
        die(3, f'ERROR PUBLISH_FAILED: status {status}')
    st.update({'msgid': rec['msgid'], 'answer_key': rec.get('answer_key'),
               'pub_bucket': dig(rec, 'scope.bucket'), 'seen': [], 'last': None,
               'agent_name': cfg['agent_name']})
    save_state(st)
    return st


def fresh_gate_notes(st, acc):
    """Gate handling. The agent never signs; it tells the human."""
    if acc.get('tos') == 'pending' and not st.get('told_pending'):
        st['told_pending'] = True
        say(f"ACTION_FOR_PRINCIPAL: sign the {acc.get('gate_document', 'Terms of Engagement')} for "
            f"this request at {BASE} ; the agent will not sign on your behalf")
    if acc.get('tos') == 'confirmed' and not acc.get('supervisor') and not st.get('told_nosup'):
        st['told_nosup'] = True
        say('WARN GATE_NO_SUPERVISOR: the gate shows confirmed but no human supervisor is bound; '
            'treating the Terms as NOT signed and not proceeding to matching')


def maybe_matches(cfg, st, acc):
    if st.get('matches_done') or acc.get('tos') != 'confirmed' or not acc.get('supervisor'):
        return
    sector = dig(cfg, 'request.sector')
    st['matches_done'] = True
    if not sector:
        say('ERROR API_PREREQUISITE: the matches call needs a sector and none is configured; '
            'this is a missing input, not an empty result')
        return
    s, r = http('GET', f"/api/matches/{acc['uuid']}?sector={sector}")
    if s == 200:
        say(f"INFO matches={r.get('count', 0)}")
    else:
        say(f'ERROR API_PREREQUISITE: matches returned {s}: {r.get("error")}')


def main():
    cfg = json.load(open(os.environ['CAPE_CONFIG'], encoding='utf-8'))
    validate(cfg)
    st = load_state()
    new = os.environ.get('CAPE_NEW_REQUEST') == '1'
    if new and not os.environ.get('CAPE_NEW_REASON'):
        die(2, 'ERROR NEW_REQUEST_NEEDS_REASON: a second record needs CAPE_NEW_REASON')
    if st.get('msgid') and not new:
        say(f"INFO already published as {st['msgid']}; polling it, not publishing again")
    else:
        if new:
            say('INFO publishing a NEW record, reason: ' + os.environ['CAPE_NEW_REASON'])
            st = {}
        if not cfg.get('location'):
            say('QUESTION location: no country or location in the brief; not assuming one')
        st = publish(cfg, st)
        if st is None:
            return
    SECRETS.add(st.get('answer_key'))
    key = st.get('answer_key') or st['msgid']
    seen, empties = set(st.get('seen', [])), 0
    last = st.get('last')
    for i in range(MAX_POLLS):
        status, ans = http('GET', f'/api/exchange/answer/{key}')
        if status != 200:
            die(3, f'ERROR POLL_FAILED: status {status}')
        if ans.get('use_this_instead') and not st.get('answer_key'):
            die(3, 'ERROR ANSWER_KEY_MISSING: the exchange says the msgid is weak and to use the '
                   'answer_key, but no answer_key was issued; stopping')
        acc = dig(ans, 'state.access') or {}
        new_msgs = [m for m in ans.get('messages', []) if m['id'] not in seen]
        for m in new_msgs:
            seen.add(m['id'])
            say(f"NEW id={m['id']} kind={m.get('kind')} created={utc(m.get('created'))}")
            link = m.get('link') or ''
            if '/answer/' in link and st['msgid'] not in link and key not in link:
                say(f"WARN STALE_LINK: message {m['id']} links to a different thread; not following")
        cur = {'tier': acc.get('tier'), 'handshake': acc.get('handshake'),
               'tos': acc.get('tos'), 'status': ans.get('submission_status')}
        changed = 0
        if last is not None:
            for k, v in cur.items():
                if last.get(k) != v:
                    say(f'CHANGE {k}: {last.get(k)} -> {v}')
                    changed += 1
        last = cur
        pb, ab = st.get('pub_bucket'), dig(ans, 'scope.bucket')
        if pb and ab and pb != ab and not st.get('warned_mismatch'):
            st['warned_mismatch'] = True
            say(f'WARN STATE_MISMATCH: publish said scope {pb}, the thread says {ab}; '
                'not re-publishing')
        if not new_msgs and not changed:
            say('NOCHANGE')
            empties += 1
        else:
            empties = 0
        # join: only against a handshake the thread itself shows as accepted
        if CONFIRM and acc.get('handshake') == 'accepted' and not st.get('uuid'):
            st['uuid'] = str(uuidlib.uuid4())
            p = cfg['principal']
            s, j = http('POST', '/api/workspace/join', {
                'uuid': st['uuid'], 'name': p['name'], 'email': p['email'],
                'company': p['company'], 'exchange_key': key})
            if s != 200:
                st['uuid'] = None
                say(f'WARN JOIN_FAILED: status {s}')
            else:
                if not j.get('delegated'):
                    say('WARN JOIN_NOT_INHERITING: no delegate was disclosed in the manifest, so '
                        'this creates a new agent workspace and does not inherit the principal\'s')
                if 'not bound' in str(j.get('principal', '')):
                    say('ACTION_FOR_PRINCIPAL: you are not yet bound to this workspace; you are '
                        'bound only when you sign the Terms at the gate step')
            empties = 0
        if acc.get('uuid'):
            fresh_gate_notes(st, acc)
            maybe_matches(cfg, st, acc)
        st['seen'], st['last'] = sorted(seen), last
        save_state(st)
        if empties >= STOP_EMPTY:
            say('INFO nothing new for several polls; backing off to the slow schedule')
            break
        time.sleep(INTERVAL)
    # closing report
    bucket = dig(ans, 'scope.bucket')
    classified = bucket in ('SERVED', 'IN_SCOPE')
    say('CANONICAL msgid=' + st['msgid'])
    say('SUMMARY:')
    say(f'  platform: {BASE} (spec {BASE}/api/exchange/spec)')
    say('  fields sent: identity, wants, offers, interface, delivery_contract, boundary')
    say(f"  msgid: {st['msgid']}")
    say('  status: ' + ('accepted, classified' if classified else 'accepted, not yet classified'))
    say('  terms: any Terms of Service or Terms of Engagement is signed by the principal, not by '
        'this agent')
    pending = (dig(ans, 'state.access.tos') in (None, 'none', 'pending')
               and dig(ans, 'state.access.uuid'))
    say('NEXT_ACTION: ' + ('principal signs the Terms of Engagement' if pending
                           else 'none, polling on the slow schedule'))


if __name__ == '__main__':
    main()
