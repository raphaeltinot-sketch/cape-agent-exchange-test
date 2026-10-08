#!/usr/bin/env python3
"""naive_agent.py - a client that repeats the mistakes recorded in the two live sessions.

It is the NEGATIVE control for agent_conformance.py: if the scenarios are any good, this agent must
fail most of them. Do not use it for anything else.

Mistakes it makes on purpose: top-level mandate; no probe-then-live; three publishes for one
request; polls with the msgid and `since`; prints the answer key; joins and signs without waiting
or asking; assumes France; reports "matched"; ignores CAPE_CONFIRM; local timestamps.
"""
import json
import os
import urllib.error
import urllib.request
import uuid

BASE = os.environ['CAPE_BASE'].rstrip('/')
cfg = json.load(open(os.environ['CAPE_CONFIG'], encoding='utf-8'))
EM = '—'


def http(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={'Content-Type': 'application/json'} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b'{}')
        except Exception:
            return e.code, {}


text = (f"identity {EM} {cfg['principal']['name']}, {cfg['principal']['company']}\n"
        f"wants {EM} a project manager, France\noffers {EM} nothing\ninterface {EM} none\n"
        f"delivery_contract {EM} data\nboundary {EM} nothing")
body = {'agent_name': cfg['agent_name'], 'manifest_text': text,
        'mandate': {'intents': [{'service_type': 'consultant_search',
                                 'scope': {'capability': 'project management'}}]}}
msgid = key = None
for _ in range(3):                      # "republish"
    s, r = http('POST', '/api/exchange/manifest', body)
    msgid, key = r.get('msgid'), r.get('answer_key') or r.get('msgid')
print('answer_key =', key)              # prints the key
s, a = http('GET', f'/api/exchange/answer/{msgid}?since=0')
print('thread status', a.get('submission_status'), a.get('note'))
u = str(uuid.uuid4())
http('POST', '/api/workspace/join', {'uuid': u, 'name': 'x', 'exchange_key': msgid})
http('POST', '/api/nda/sign', {'session_id': u, 'signer_name': cfg['principal']['name']})
http('POST', '/api/nda/sign', {'session_id': u, 'signer_name': cfg['principal']['name']})
http('GET', f'/api/matches/{u}')
print('Done. The Terms are signed and your project manager request is matched.')
