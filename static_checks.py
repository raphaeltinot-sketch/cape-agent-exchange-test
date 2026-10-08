#!/usr/bin/env python3
"""static_checks.py - read an agent's source tree and check what HTTP tests cannot see.

    python static_checks.py path/to/agent-repo
    python static_checks.py path/to/agent-repo --forbid "ClientName,principal@their-domain.tld" --history

Checks (IDs match cape-exchange-test-book.md):
  S-01  nothing in the code calls a signing endpoint outside a human-only module
  S-04  no print/log statement writes a key or secret variable
  S-05  no key-like secret committed in the tree (and, with --history, in git history)
  S-06  every file that publishes live also mentions a human confirmation switch
  I-01  principal / company / email data is not hard-coded in code (only in config)
  L-05  no naive (timezone-less) timestamps
  T-02  the exchange base URL is overridable, so tests can point at the test server
  H-01  .gitignore covers state files, .env and key files

Results: PASS, FAIL, REVIEW (a heuristic hit that needs a human look). Exit 1 if any FAIL.
"""
import argparse
import fnmatch
import os
import re
import subprocess
import sys

CODE_EXT = {'.py', '.js', '.ts', '.mjs', '.sh', '.ps1', '.rb', '.go', '.java', '.cs'}
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'dist', 'build'}
CONFIG_HINT = re.compile(r'(config|settings|fixture|example|sample|test)', re.I)


def walk(root):
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            yield os.path.join(d, f)


def read(p):
    try:
        return open(p, encoding='utf-8', errors='replace').read()
    except OSError:
        return ''


def lines_with(text, rx, flags=re.I):
    return [(i + 1, l.strip()) for i, l in enumerate(text.splitlines()) if re.search(rx, l, flags)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path')
    ap.add_argument('--forbid', default='',
                    help='comma-separated strings that must not be hard-coded in code')
    ap.add_argument('--human-glob', default='*human*,*principal*',
                    help='file globs allowed to call signing endpoints')
    ap.add_argument('--history', action='store_true', help='also scan git history for secrets')
    ap.add_argument('--self-exclude', default='', help='comma-separated paths to skip')
    args = ap.parse_args()
    root = os.path.abspath(args.path)
    skip = [os.path.abspath(p) for p in args.self_exclude.split(',') if p]
    human = args.human_glob.split(',')
    files = [p for p in walk(root) if not any(os.path.abspath(p).startswith(s) for s in skip)]
    code = [p for p in files if os.path.splitext(p)[1] in CODE_EXT]
    rel = lambda p: os.path.relpath(p, root)       # noqa: E731
    res = []

    def add(id_, status, title, hits=()):
        res.append((id_, status, title, list(hits)[:6]))

    # S-01
    hits = []
    for p in code:
        if any(fnmatch.fnmatch(os.path.basename(p).lower(), g) for g in human):
            continue
        for n, l in lines_with(read(p), r'nda/sign|/sign\b|signed_at|sign_nda|sign_terms'):
            hits.append(f'{rel(p)}:{n}: {l[:90]}')
    add('S-01', 'FAIL' if hits else 'PASS', 'no signing call outside a human-only module', hits)

    # S-04
    hits = []
    for p in code:
        for n, l in lines_with(read(p), r'(print|log\w*\.\w+|logger\.\w+|console\.\w+|echo)\s*\(?.*'
                                        r'\b(answer_key|api_key|secret|token|password)\b'):
            if 'REDACT' in l.upper() or re.search(r'(?i)print\(.*(has|set|present|bool)', l):
                continue
            hits.append(f'{rel(p)}:{n}: {l[:90]}')
    add('S-04', 'REVIEW' if hits else 'PASS', 'no print/log of key or secret variables', hits)

    # S-05
    rx = r'(answer_key|api[_-]?key|secret|token|exchange_key)["\']?\s*[=:]\s*["\']?[0-9a-f]{32}\b'
    hits = [f'{rel(p)}:{n}: {l[:90]}' for p in files for n, l in lines_with(read(p), rx)
            if not CONFIG_HINT.search(rel(p)) or 'TEST' not in l.upper()]
    if args.history and os.path.isdir(os.path.join(root, '.git')):
        try:
            out = subprocess.run(['git', '-C', root, 'log', '-p', '--all', '-G', rx],
                                 capture_output=True, text=True, errors='replace').stdout
            if re.search(rx, out, re.I):
                hits.append('git history contains a key-like value (run: git log -p --all -G"...")')
        except OSError:
            pass
    add('S-05', 'FAIL' if hits else 'PASS', 'no key-like secret in the tree' +
        (' or history' if args.history else ''), hits)

    # S-06
    hits = []
    for p in code:
        t = read(p)
        if re.search(r'api/exchange/manifest|api/workspace/join', t) and \
                not re.search(r'(?im)^\s*(if|elif|assert)\b.*(confirm|--yes|approved?\b)', t):
            hits.append(f'{rel(p)}: publishes/joins with no conditional on a confirmation switch')
    add('S-06', 'FAIL' if hits else 'PASS', 'live publish/join sits behind a human confirmation', hits)

    # I-01
    forbid = [f for f in args.forbid.split(',') if f]
    hits = []
    for p in code:
        if CONFIG_HINT.search(os.path.basename(p)):
            continue
        t = read(p)
        for f in forbid:
            for n, l in lines_with(t, re.escape(f)):
                hits.append(f'{rel(p)}:{n}: {f}: {l[:70]}')
        for n, l in lines_with(t, r'[\w.+-]+@[\w-]+\.[a-z]{2,}'):
            if not re.search(r'example\.(com|test|org)|@(types|param)|noreply', l, re.I):
                hits.append(f'{rel(p)}:{n}: email literal: {l[:70]}')
    add('I-01', 'FAIL' if hits else 'PASS', 'no principal, company, email or URL hard-coded in code', hits)

    # L-05
    hits = []
    for p in code:
        for n, l in lines_with(read(p), r'datetime\.now\(\s*\)|datetime\.utcnow\(|time\.localtime|'
                                        r'time\.ctime|toLocale(Time|Date)?String|new Date\(\)\.to(String|DateString)'):
            hits.append(f'{rel(p)}:{n}: {l[:90]}')
    add('L-05', 'REVIEW' if hits else 'PASS', 'timestamps are timezone-aware (UTC)', hits)

    # T-02
    hits = []
    for p in code:
        t = read(p)
        if re.search(r'capepartners\.fr', t) and not re.search(
                r'(?i)CAPE_BASE|--base|BASE_URL|base_url|environ|process\.env', t):
            hits.append(f'{rel(p)}: production URL with no override')
    add('T-02', 'FAIL' if hits else 'PASS', 'exchange base URL can be overridden (tests need it)', hits)

    # H-01
    gi = read(os.path.join(root, '.gitignore'))
    missing = [x for x in ('.env', 'state', '*.key') if x not in gi]
    add('H-01', 'REVIEW' if missing else 'PASS', '.gitignore covers state, .env and key files',
        [f'.gitignore lacks: {", ".join(missing)}'] if missing else [])

    w = max(len(r[2]) for r in res)
    for id_, st, title, hits in res:
        print(f'[{st:6}] {id_:5} {title}')
        for h in hits:
            print(f'           - {h}')
    fails = sum(1 for r in res if r[1] == 'FAIL')
    reviews = sum(1 for r in res if r[1] == 'REVIEW')
    print(f'\n{len(res) - fails - reviews} pass, {fails} fail, {reviews} need review')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
