#!/usr/bin/env python3
"""agent_conformance.py - run an AGENT against the test server and check what it did and said.

    python agent_conformance.py --agent "python agents/reference_agent.py"
    python agent_conformance.py --agent "python agents/naive_agent.py" --only P-03,S-01
    python agent_conformance.py --agent "<your command>" --json report.json

The agent is started once per run with the environment documented in agents/reference_agent.py.
It never touches the live exchange: the harness starts server.py on a free port and points the
agent at it. Exit status is 1 if any BLOCKER fails (or, with --strict, any test fails).
"""
import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tests'))
from testbook import check, jget          # noqa: E402
from agent_scenarios import CFG, SCENARIOS    # noqa: E402

SEV = {'B': 'BLOCKER', 'M': 'MAJOR', 'm': 'MINOR'}


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


def call(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={'Content-Type': 'application/json'} if data else {})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read() or b'{}')


def set_path(d, dotted, value):
    parts = dotted.split('.')
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = value


def req_matches(r, f):
    if f.get('method') and r['method'] != f['method']:
        return False
    if f.get('path') and not re.search(f['path'], r['path']):
        return False
    if 'probe' in f and r['probe'] != f['probe']:
        return False
    return True


def op_ok(op, actual, want):
    return check(op, actual, want)


def read_files(workdir, skip):
    blobs = []
    for root, _, files in os.walk(workdir):
        for fn in files:
            p = os.path.join(root, fn)
            if os.path.abspath(p) == os.path.abspath(skip):
                continue
            try:
                blobs.append(open(p, encoding='utf-8', errors='replace').read())
            except OSError:
                pass
    return '\n'.join(blobs)


def evaluate(a, ctx):
    """Return (ok, detail)."""
    kind = a[0]
    reqs, stats, sec = ctx['requests'], ctx['stats'], ctx['secrets']
    out = ctx['out']
    if kind == 'stat':
        _, key, op, n = a
        return op_ok(op, stats.get(key), n), f'{key}={stats.get(key)} (want {op} {n})'
    if kind == 'req':
        _, f, op, n = a
        c = sum(1 for r in reqs if req_matches(r, f))
        return op_ok(op, c, n), f'{c} matching request(s) (want {op} {n})'
    if kind == 'every':
        _, f, wheres = a
        hits = [r for r in reqs if req_matches(r, f)]
        if not hits:
            return False, 'no matching request was made'
        for r in hits:
            for path, op, val in wheres:
                found, actual = jget(r, path)
                if not op_ok(op, actual if found else None, val):
                    shown = repr(actual)[:70] if found else '<absent>'
                    return False, f'request #{r["n"]}: {path} {op} {val!r} failed (got {shown})'
        return True, f'{len(hits)} request(s) ok'
    if kind == 'out':
        _, mode, rx = a
        found = re.search(rx, out, re.M | re.I) is not None
        return (found if mode == 'has' else not found), f'output {mode} /{rx}/'
    if kind == 'outn':
        _, rx, op, n = a
        c = len(re.findall(rx, out, re.M | re.I))
        return op_ok(op, c, n), f'{c} line(s) match /{rx}/ (want {op} {n})'
    if kind == 'exit':
        _, op, n = a
        return op_ok(op, ctx['exit'], n), f'exit code {ctx["exit"]} (want {op} {n})'
    if kind == 'probe_before_live':
        lives = [r for r in reqs if req_matches(r, {'method': 'POST', 'path': r'^/api/exchange/manifest$', 'probe': False})]
        if not lives:
            return False, 'no live publish happened'
        for L in lives:
            want = {k: v for k, v in (L['body'] or {}).items() if k != 'probe'}
            ok = any(r['n'] < L['n'] and r['probe'] and r['status'] == 200 and
                     {k: v for k, v in (r['body'] or {}).items() if k != 'probe'} == want
                     for r in reqs if r['path'] == '/api/exchange/manifest')
            if not ok:
                return False, f'live publish #{L["n"]} had no earlier PASS probe of the same body'
        return True, f'{len(lives)} live publish(es) each preceded by an identical probe'
    if kind == 'no_poll_of':
        ids = sec.get(a[1], [])
        bad = [r for r in reqs if r['method'] == 'GET' and any(i in r['path'] for i in ids)]
        return (not bad and bool(ids)), f'{len(ids)} probe msgid(s) issued, {len(bad)} polled'
    if kind == 'polls_use_answer_key':
        keys = sec.get('answer_keys', [])
        polls = [r for r in reqs if req_matches(r, {'method': 'GET', 'path': r'^/api/exchange/answer/'})]
        if not polls or not keys:
            return False, 'no polls or no answer_key issued'
        bad = [r for r in polls if r['path'].rsplit('/', 1)[-1] not in keys]
        return not bad, f'{len(polls)} poll(s), {len(bad)} not using the answer_key'
    if kind == 'has_all':
        ids = sec.get(a[1], [])
        missing = [i for i in ids if i not in out]
        return (bool(ids) and not missing), f'{len(ids) - len(missing)}/{len(ids)} msgid(s) reported'
    if kind == 'secrets_hidden':
        keys = sec.get('answer_keys', [])
        blob = out + '\n' + read_files(ctx['workdir'], ctx['state_file'])
        leaked = [k for k in keys if k in blob]
        return (bool(keys) and not leaked), f'{len(keys)} key(s) issued, {len(leaked)} leaked outside the state file'
    if kind == 'state_has_key':
        keys = sec.get('answer_keys', [])
        try:
            st = json.load(open(ctx['state_file'], encoding='utf-8'))
        except Exception:
            st = {}
        return (bool(keys) and st.get('answer_key') in keys), f'state file answer_key={bool(st.get("answer_key"))}'
    return False, f'unknown assertion {kind}'


def run_scenario(sc, base, agent_cmd, keep):
    call(base, 'POST', '/_test/reset', {})
    call(base, 'POST', '/_test/config', {'quirks': sc['quirks'], 'on_publish_messages': sc['msgs']})
    cfg = json.loads(json.dumps(CFG))
    for k, v in sc['cfg'].items():
        set_path(cfg, k, v)
    root = tempfile.mkdtemp(prefix='cape-conf-')
    workdir = root
    out, code = '', None
    try:
        for i, run in enumerate(sc['runs']):
            if run.get('fresh'):
                workdir = tempfile.mkdtemp(prefix='cape-conf-', dir=root)
            cfg_path = os.path.join(workdir, 'config.json')
            json.dump(cfg, open(cfg_path, 'w', encoding='utf-8'))
            state_file = os.path.join(workdir, 'state.json')
            env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
                       CAPE_BASE=sc['base'] or base, CAPE_CONFIG=cfg_path, CAPE_WORKDIR=workdir,
                       CAPE_STATE_FILE=state_file, CAPE_CONFIRM='1' if sc['confirm'] else '0',
                       CAPE_MAX_POLLS='3', CAPE_STOP_AFTER_EMPTY='3', CAPE_POLL_INTERVAL='0')
            env.update(sc['env'])
            env.update(run.get('env', {}))
            p = subprocess.run(agent_cmd, shell=True, cwd=HERE, env=env, capture_output=True,
                               text=True, encoding='utf-8', errors='replace', timeout=120)
            out += p.stdout + p.stderr
            code = p.returncode
        ctx = {'requests': call(base, 'GET', '/_test/requests')['requests'],
               'stats': call(base, 'GET', '/_test/stats'),
               'secrets': call(base, 'GET', '/_test/secrets'),
               'out': out, 'exit': code, 'workdir': root, 'state_file': state_file}
        results = []
        for a in sc['asserts']:
            try:
                ok, detail = evaluate(a, ctx)
            except Exception as e:      # a broken assertion is a failure, never a pass
                ok, detail = False, f'assertion error: {e}'
            results.append((a[0], ok, detail))
        return results, out
    finally:
        if not keep:
            shutil.rmtree(root, ignore_errors=True)


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    ap = argparse.ArgumentParser(description='Run an agent against the test server.')
    ap.add_argument('--agent', required=True, help='command that runs the agent once')
    ap.add_argument('--only', help='comma-separated scenario ids')
    ap.add_argument('--base', help='use an already-running server instead of starting one')
    ap.add_argument('--json', help='write the full report here')
    ap.add_argument('--strict', action='store_true', help='fail on any failed test, not only blockers')
    ap.add_argument('--verbose', action='store_true', help='show agent output for failures')
    ap.add_argument('--keep', action='store_true', help='keep temp work dirs')
    args = ap.parse_args()

    server, base = None, args.base
    if not base:
        port = free_port()
        server = subprocess.Popen([sys.executable, os.path.join(HERE, 'server.py'), '--port', str(port)],
                                  stdout=subprocess.DEVNULL)
        base = f'http://127.0.0.1:{port}'
        for _ in range(50):
            try:
                urllib.request.urlopen(base + '/healthz', timeout=1)
                break
            except Exception:
                time.sleep(0.1)
    only = set(args.only.split(',')) if args.only else None
    report, tally = [], {'B': [0, 0], 'M': [0, 0], 'm': [0, 0]}
    try:
        for sc in SCENARIOS:
            if only and sc['id'] not in only:
                continue
            results, out = run_scenario(sc, base, args.agent, args.keep)
            ok = all(r[1] for r in results)
            tally[sc['sev']][0 if ok else 1] += 1
            print(f'[{"PASS" if ok else "FAIL"}] {sc["id"]:6} {SEV[sc["sev"]]:8} {sc["title"]}', flush=True)
            if not ok:
                for kind, r_ok, detail in results:
                    if not r_ok:
                        print(f'          X {kind}: {detail}')
                if args.verbose:
                    print('          --- agent output ---')
                    print('\n'.join('          ' + l for l in out.splitlines()[-25:]))
            report.append({'id': sc['id'], 'title': sc['title'], 'severity': SEV[sc['sev']], 'pass': ok,
                           'assertions': [{'kind': k, 'pass': o, 'detail': d} for k, o, d in results]})
    finally:
        if server:
            server.terminate()
            try:
                server.wait(timeout=5)
            except Exception:
                server.kill()
    print('\nScorecard (pass/fail):')
    for k in ('B', 'M', 'm'):
        print(f'  {SEV[k]:8} {tally[k][0]:3} / {tally[k][1]:3}')
    if args.json:
        json.dump(report, open(args.json, 'w', encoding='utf-8'), indent=1)
    blockers_failed = tally['B'][1] > 0
    any_failed = sum(t[1] for t in tally.values()) > 0
    verdict = 'REJECT (a BLOCKER failed)' if blockers_failed else (
        'ACCEPT with fixes (MAJOR/MINOR failures)' if any_failed else 'ACCEPT')
    print('Verdict:', verdict)
    sys.exit(1 if blockers_failed or (args.strict and any_failed) else 0)


if __name__ == '__main__':
    main()
