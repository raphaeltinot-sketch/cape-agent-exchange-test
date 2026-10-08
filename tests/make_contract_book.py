import json
import sys

UUID = '11111111-1111-4111-8111-111111111111'
EM = '—'


def text(identity='principal: Test Co, pm@example.test'):
    return (f'identity {EM} {identity}\nwants {EM} a project manager for 3 months\n'
            f'offers {EM} nothing\ninterface {EM} I poll every 6 hours\n'
            f'delivery_contract {EM} data\nboundary {EM} nothing')


def mandate(scope):
    return {'intents': [{'direction': 'buy', 'service_type': 'consultant_search', 'scope': scope}]}


def body(name='contract-agent', nested=True, toplevel=False, scope=None, probe=False, identity=None):
    b = {'agent_name': name, 'manifest_text': text(identity) if identity else text()}
    if probe:
        b['probe'] = True
    if nested:
        b['manifest'] = {'mandate': mandate(scope or {'capability': 'project management'})}
    if toplevel:
        b['mandate'] = mandate(scope or {'capability': 'project management'})
    return b


cases = []


def case(name, method, path, req_body=None, status=None, js=None, capture=None):
    c = {'name': name, 'request': {'method': method, 'path': path}}
    if req_body is not None:
        c['request']['body'] = req_body
    if capture:
        c['capture'] = capture
    exp = {}
    if status is not None:
        exp['status'] = status
    if js:
        exp['json'] = [{'path': p, 'op': o, **({'value': v} if v is not _N else {})} for p, o, v in js]
    c['expect'] = exp
    cases.append(c)


_N = object()


def reset():
    case('(setup) reset server state', 'POST', '/_test/reset', {}, 200, [('ok', 'eq', True)])


def cfg(quirks=None, msgs=None):
    case('(setup) configure quirks ' + ','.join(quirks or []), 'POST', '/_test/config',
         {'quirks': quirks or [], 'on_publish_messages': msgs or []}, 200, [('ok', 'eq', True)])


def pub(name, b, capture=None, status=200, js=None):
    case(name, 'POST', '/api/exchange/manifest', b, status, js or [], capture)


# M-01
reset()
case('M-01 a fresh server holds no records', 'GET', '/_test/stats', None, 200,
     [('records', 'eq', 0), ('requests', 'eq', 0)])

# M-02 / M-03 nesting
pub('M-02 a top-level mandate is not read: scope UNDECIDED', body(nested=False, toplevel=True),
    js=[('scope.bucket', 'eq', 'UNDECIDED')])
pub('M-03 a nested mandate is read: scope SERVED', body(), {'msgid': 'msgid'},
    js=[('scope.bucket', 'eq', 'SERVED'), ('msgid', 'exists', _N)])
case('M-03b the thread agrees with the receipt (default server)', 'GET',
     '/api/exchange/answer/${msgid}', None, 200,
     [('scope.bucket', 'eq', 'SERVED'), ('state.access.tier', 'eq', 1),
      ('state.access.handshake', 'eq', 'accepted'), ('use_this_instead', 'absent', _N)])

# M-04 spec vs probe
reset()
cfg(['strict_scope', 'spec_sector'])
case('M-04a the SPEC says consultant_search needs sector', 'GET', '/api/exchange/spec', None, 200,
     [('catalog.services.10.service_type', 'eq', 'consultant_search'),
      ('catalog.services.10.required.0', 'eq', 'sector')])
pub('M-04b a probe with only sector fails: the probe wants capability',
    body(probe=True, scope={'sector': 'Consulting'}), status=422,
    js=[('verdict', 'eq', 'FAIL'), ('required_by_service.consultant_search.0', 'eq', 'capability')])
pub('M-04c a probe with capability passes', body(probe=True), status=200,
    js=[('verdict', 'eq', 'PASS'), ('recorded', 'eq', False)])

# M-05 publish vs thread disagree
reset()
cfg(['answer_undecided'])
pub('M-05a receipt says SERVED', body(), {'msgid': 'msgid'}, js=[('scope.bucket', 'eq', 'SERVED')])
case('M-05b ...but the thread reads UNDECIDED', 'GET', '/api/exchange/answer/${msgid}', None, 200,
     [('scope.bucket', 'eq', 'UNDECIDED')])

# M-06 weak msgid
reset()
cfg(['weak_msgid'])
pub('M-06a a weak-msgid receipt carries an answer_key', body(), {'msgid': 'msgid', 'akey': 'answer_key'},
    js=[('answer_key', 'matches', '^[0-9a-f]{32}$')])
case('M-06b the thread by msgid says use the answer_key', 'GET', '/api/exchange/answer/${msgid}', None,
     200, [('use_this_instead', 'contains', 'answer_key')])
case('M-06c the answer_key reads the same thread', 'GET', '/api/exchange/answer/${akey}', None, 200,
     [('found', 'eq', True), ('total_messages', 'ge', 1)])

# M-07 null answer key
reset()
cfg(['weak_msgid', 'null_answer_key'])
pub('M-07 the receipt answer_key is null while the thread demands one', body(),
    js=[('answer_key', 'absent', _N)])

# M-08 since quirk
reset()
cfg(['since_no_answer_yet'])
pub('M-08a publish', body(), {'msgid': 'msgid'})
case('M-08b a delta poll with nothing new says "No answer yet" (the live defect)', 'GET',
     '/api/exchange/answer/${msgid}?since=999999', None, 200,
     [('count', 'eq', 0), ('total_messages', 'ge', 1), ('note', 'contains', 'No answer yet')])

# M-09 probe returns a msgid
reset()
cfg(['probe_returns_msgid'])
pub('M-09a a probe receipt carries a msgid but records nothing', body(probe=True),
    {'pmsgid': 'msgid'}, js=[('recorded', 'eq', False), ('msgid', 'exists', _N)])
case('M-09b that msgid is a 404', 'GET', '/api/exchange/answer/${pmsgid}', None, 404,
     [('found', 'eq', False)])

# M-10 join
reset()
pub('M-10a publish', body(), {'msgid': 'msgid'})
case('M-10b join returns an agent-named, unverified, undelegated workspace', 'POST',
     '/api/workspace/join',
     {'uuid': UUID, 'name': 'G Test', 'email': 'pm@example.test', 'company': 'Test Co',
      'exchange_key': '${msgid}'}, 200,
     [('uuid', 'eq', UUID), ('name', 'matches', '^agent:contract-agent$'),
      ('identity_recorded', 'contains', 'UNVERIFIED'), ('delegated', 'eq', False),
      ('principal', 'contains', 'not bound')])
case('M-10c the thread now shows tier 2 and the uuid', 'GET', '/api/exchange/answer/${msgid}', None,
     200, [('state.access.tier', 'eq', 2), ('state.access.uuid', 'eq', UUID),
           ('state.access.tos', 'eq', 'none')])
case('M-11 join with an unknown key is a 404', 'POST', '/api/workspace/join',
     {'uuid': UUID, 'exchange_key': 'nope'}, 404, [('ok', 'eq', False)])

# M-12 hold acceptance
reset()
cfg(['hold_acceptance'])
pub('M-12a publish', body(), {'msgid': 'msgid'})
case('M-12b no acceptance on the thread; handshake pending', 'GET', '/api/exchange/answer/${msgid}',
     None, 200, [('total_messages', 'eq', 0), ('state.access.handshake', 'eq', 'pending')])
case('M-12c join before acceptance is refused', 'POST', '/api/workspace/join',
     {'uuid': UUID, 'exchange_key': '${msgid}'}, 409, [('ok', 'eq', False)])

# M-13 sign flow with a human
reset()
pub('M-13a publish', body(), {'msgid': 'msgid'})
case('M-13b join', 'POST', '/api/workspace/join', {'uuid': UUID, 'exchange_key': '${msgid}'}, 200)
case('M-13c an agent sign request is only a request', 'POST', '/api/nda/sign',
     {'session_id': UUID, 'signer_name': 'G Test', 'company': 'Test Co'}, 202,
     [('nda_signed', 'eq', False), ('pending_human_approval', 'eq', True)])
case('M-13d the gate is pending', 'GET', '/api/exchange/answer/${msgid}', None, 200,
     [('state.access.tos', 'eq', 'pending'), ('state.access.supervisor', 'absent', _N)])
case('M-13e a human approval confirms it and binds a supervisor', 'POST', '/_test/human/approve',
     {'session_id': UUID}, 200, [('tos', 'eq', 'confirmed')])
case('M-13f the gate is confirmed with a supervisor', 'GET', '/api/exchange/answer/${msgid}', None,
     200, [('state.access.tos', 'eq', 'confirmed'), ('state.access.supervisor', 'exists', _N)])

# M-14 auto confirm defect
reset()
cfg(['auto_confirm_gate'])
pub('M-14a publish', body(), {'msgid': 'msgid'})
case('M-14b join', 'POST', '/api/workspace/join', {'uuid': UUID, 'exchange_key': '${msgid}'}, 200)
case('M-14c first sign request is pending', 'POST', '/api/nda/sign', {'session_id': UUID}, 202)
case('M-14d second sign request "confirms" with no human (the live defect)', 'POST', '/api/nda/sign',
     {'session_id': UUID}, 200, [('nda_signed', 'eq', True)])
case('M-14e the gate is confirmed and no supervisor is bound', 'GET', '/api/exchange/answer/${msgid}',
     None, 200, [('state.access.tos', 'eq', 'confirmed'), ('state.access.supervisor', 'absent', _N)])

# M-15 matches need a sector
reset()
pub('M-15a publish', body(), {'msgid': 'msgid'})
case('M-15b join', 'POST', '/api/workspace/join', {'uuid': UUID, 'exchange_key': '${msgid}'}, 200)
case('M-15c matches without a sector is a 404 that names the sector', 'GET', '/api/matches/' + UUID,
     None, 404, [('error', 'contains', 'needs sector')])
case('M-15d matches with a sector is a 200', 'GET', '/api/matches/' + UUID + '?sector=Consulting',
     None, 200, [('count', 'eq', 0)])
case('M-15e matched-names is a 200 and empty', 'GET', '/api/matched-names/' + UUID, None, 200,
     [('names', 'eq', [])])

# M-16 scripted thread messages
reset()
cfg([], [{'kind': 'nudge', 'body': 'no mandate declared', 'category': 'mandate_declaration'},
         {'kind': 'notice', 'body': 'Your manifest is accepted.'}])
pub('M-16a publish', body(), {'msgid': 'msgid'})
case('M-16b the scripted messages follow the acceptance', 'GET', '/api/exchange/answer/${msgid}', None,
     200, [('total_messages', 'eq', 3), ('messages.1.category', 'eq', 'mandate_declaration')])

# M-17 delegate disclosure
reset()
pub('M-17a publish with a delegate disclosed in identity',
    body(identity='principal: Test Co; agent acts as delegate of G Test (workspace ws-test-1)'),
    {'msgid': 'msgid'})
case('M-17b join then inherits', 'POST', '/api/workspace/join',
     {'uuid': UUID, 'exchange_key': '${msgid}'}, 200,
     [('delegated', 'eq', True), ('inherited_uuid', 'eq', True)])

# M-18 request recorder
reset()
pub('M-18a probe', body(probe=True))
pub('M-18b live', body())
case('M-18c the recorder counts both and does not count its own /_test calls', 'GET',
     '/_test/stats', None, 200,
     [('manifest_probe', 'eq', 1), ('manifest_live', 'eq', 1), ('records', 'eq', 1),
      ('requests', 'eq', 2)])

out = {'book': 'Contract book - the test server reproduces the behaviours seen in the two live sessions',
       'cases': cases}
json.dump(out, open(sys.argv[1], 'w', encoding='utf-8', newline='\n'), indent=1, ensure_ascii=True)
print(len(cases), 'cases')
