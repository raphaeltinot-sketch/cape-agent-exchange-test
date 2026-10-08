#!/usr/bin/env python3
"""testbook.py — run a JSON test book against the Cape Agent Exchange (or this test server).

A "test book" is a list of cases; each case is one HTTP request plus assertions on the
response. Values captured from one response (e.g. the msgid) can be used in later cases with
`${name}` substitution, so a book can drive a whole flow: post a manifest, then poll its thread.

    python3 testbook.py --base http://localhost:8080 tests/sample_test_book.json
    python3 testbook.py --serve tests/sample_test_book.json      # start the bundled server itself

Book format (JSON):

    {
      "book": "Agent Exchange — smoke",
      "base": "http://localhost:8080",          # optional; --base overrides
      "cases": [
        {
          "name": "the spec is served",
          "request": {"method": "GET", "path": "/api/exchange/spec"},
          "expect": {"status": 200,
                     "json": [{"path": "name", "op": "contains", "value": "Cape"}]}
        },
        {
          "name": "post a manifest and keep its msgid",
          "request": {"method": "POST", "path": "/api/exchange/manifest",
                      "body": {"agent_name": "book-demo", "manifest_text": "identity — …\\n"}},
          "capture": {"msgid": "msgid"},
          "expect": {"status": 200, "json": [{"path": "msgid", "op": "exists"}]}
        },
        {
          "name": "poll it",
          "request": {"method": "GET", "path": "/api/exchange/answer/${msgid}"},
          "expect": {"status": 200, "json": [{"path": "found", "op": "eq", "value": true}]}
        }
      ]
    }

Ops: eq, ne, contains, not_contains, exists, absent, gt, ge, lt, le, matches (regex), in, not_in.

Exit status: 0 when every case passes, 1 otherwise. Prints one PASS/FAIL line per assertion.
"""
import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p

OPS = {'eq', 'ne', 'contains', 'not_contains', 'exists', 'absent', 'gt', 'ge', 'lt', 'le',
       'matches', 'in', 'not_in'}


def jget(obj, path):
    """Traverse a dict/list by a dotted path ('a.b.0.c'). Returns (found, value)."""
    cur = obj
    for part in [p for p in str(path).split('.') if p != '']:
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return False, None
    return True, cur


def substitute(obj, ctx):
    """Replace ${name} in every string of a nested structure from ctx."""
    if isinstance(obj, str):
        def repl(m):
            return str(ctx.get(m.group(1), m.group(0)))
        return re.sub(r'\$\{([A-Za-z0-9_]+)\}', repl, obj)
    if isinstance(obj, dict):
        return {k: substitute(v, ctx) for k, v in obj.items()}
    if isinstance(obj, list):
        return [substitute(v, ctx) for v in obj]
    return obj


def check(op, actual, expected):
    if op == 'exists':
        return actual is not None
    if op == 'absent':
        return actual is None
    if op == 'eq':
        return actual == expected
    if op == 'ne':
        return actual != expected
    if op == 'contains':
        return isinstance(actual, (str, list)) and expected in actual
    if op == 'not_contains':
        return not (isinstance(actual, (str, list)) and expected in actual)
    if op == 'gt':
        return actual is not None and actual > expected
    if op == 'ge':
        return actual is not None and actual >= expected
    if op == 'lt':
        return actual is not None and actual < expected
    if op == 'le':
        return actual is not None and actual <= expected
    if op == 'matches':
        return isinstance(actual, str) and re.search(expected, actual) is not None
    if op == 'in':
        return actual in expected
    if op == 'not_in':
        return actual not in expected
    raise ValueError(f'unknown op: {op}')


def http(method, url, body=None, headers=None, timeout=30):
    data = None
    h = {'User-Agent': 'cape-agent-exchange-testbook/1.0'}
    h.update(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        h.setdefault('Content-Type', 'application/json')
    req = urllib.request.Request(url, data=data, headers=h, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = None
    return status, parsed, raw.decode('utf-8', 'replace')


def run_case(case, base, ctx):
    """Return (ok, [ (label, passed, detail) ])."""
    req = case.get('request') or {}
    method = req.get('method', 'GET')
    path = substitute(req.get('path', ''), ctx)
    body = substitute(req.get('body'), ctx) if req.get('body') is not None else None
    url = base.rstrip('/') + path
    status, parsed, text = http(method, url, body, req.get('headers'))

    # capture values for later cases before asserting
    for name, jpath in (case.get('capture') or {}).items():
        _, val = jget(parsed, jpath)
        ctx[name] = val

    results = []
    exp = case.get('expect') or {}
    if 'status' in exp:
        want = exp['status']
        ok = status in want if isinstance(want, list) else status == want
        results.append((f'status == {want}', ok, f'got {status}'))
    for a in exp.get('json', []):
        found, actual = jget(parsed, a['path'])
        op = a.get('op', 'eq')
        if op not in OPS:
            results.append((f'{a["path"]} {op}', False, 'unknown op'))
            continue
        try:
            ok = check(op, actual if found else None, a.get('value'))
        except Exception as e:
            ok = False
            results.append((f'{a["path"]} {op}', False, f'error: {e}'))
            continue
        shown = repr(actual)[:80] if found else '<absent>'
        results.append((f'{a["path"]} {op} {a.get("value")!r}', ok, f'got {shown}'))
    for r in exp.get('text', []):
        ok = check(r.get('op', 'contains'), text, r.get('value'))
        results.append((f'body {r.get("op","contains")} {r.get("value")!r}', ok, ''))
    if not results:
        results.append(('(no assertions)', True, ''))
    return all(r[1] for r in results), results


def main():
    ap = argparse.ArgumentParser(description='Run a JSON test book against the Agent Exchange.')
    ap.add_argument('books', nargs='+', help='one or more test-book JSON files')
    ap.add_argument('--base', default=None, help='base URL (overrides the book\'s "base")')
    ap.add_argument('--serve', action='store_true',
                    help='start the bundled server.py on a free port first')
    ap.add_argument('--port', type=int, default=0,
                    help='port for the bundled server (0 = pick a free port)')
    args = ap.parse_args()

    server = None
    base = args.base
    if args.serve:
        port = args.port or free_port()
        server = subprocess.Popen([sys.executable, os.path.join(HERE, 'server.py'),
                                   '--port', str(port)])
        base = base or f'http://127.0.0.1:{port}'
        for _ in range(50):
            try:
                urllib.request.urlopen(base + '/healthz', timeout=1)
                break
            except Exception:
                time.sleep(0.1)

    total = passed = 0
    try:
        for book_path in args.books:
            book = json.load(open(book_path))
            b = (base or book.get('base') or 'http://localhost:8090')
            print(f'== {book.get("book", os.path.basename(book_path))}  (base {b}) ==', flush=True)
            ctx = {}
            for case in book.get('cases', []):
                ok, results = run_case(case, b, ctx)
                total += 1
                passed += 1 if ok else 0
                print(f'[{"PASS" if ok else "FAIL"}] {case.get("name","(unnamed)")}', flush=True)
                for label, r_ok, detail in results:
                    mark = 'ok ' if r_ok else 'X  '
                    print(f'        {mark} {label}' + (f'  — {detail}' if detail else ''), flush=True)
    finally:
        if server:
            server.terminate()
            try:
                server.wait(timeout=5)
            except Exception:
                server.kill()

    print(f'\n{passed}/{total} cases passed', flush=True)
    sys.exit(0 if passed == total else 1)


if __name__ == '__main__':
    main()
