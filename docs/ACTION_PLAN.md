# Action plan for the coding agent

Generated from `tests/make_plan.py` (do not edit by hand). Machine-readable twin: `docs/findings.json`. Test list: `docs/tests-index.json`.

## How to work

1. Read `AGENTS.md`, then this file, top to bottom.
2. Take tasks in priority order (T1, T2, T3 first: they are BLOCKERs and independent).
3. For each task: run its tests, see them fail, change **your agent**, run again.
   `python agent_conformance.py --agent "<cmd>" --only P-03,P-04 --verbose`
4. Commit per task with the task id in the message. Run the full suite before moving on.
5. Finish with the definition of done below and write `results/notes.md`.

## Definition of done

- `python agent_conformance.py --agent "<your agent command>" --strict --json results/latest.json`
- `python static_checks.py <path to your agent repo> --history --forbid "<client name>,<principal email domain>"`
- `python testbook.py --serve tests/sample_test_book.json tests/contract_book.json`

conformance prints "Verdict: ACCEPT" with 0 failures; static_checks has 0 FAIL and every REVIEW is explained in results/notes.md; the contract books pass.

## Rules

- Never call the live exchange (https://www.capepartners.fr) from tests or while developing.
- Never sign, or call a signing endpoint, on behalf of the principal.
- Do not edit tests/agent_scenarios.py, tests/contract_book.json or the assertions in agent_conformance.py to make a test pass. If a test is wrong, say so in results/notes.md.
- New live behaviour found later: add a quirk to server.py and a scenario, in a separate commit.
- Do not commit keys, msgids, uuids, real emails or real company names.

## Tasks

| Task | Priority | Severity | Depends on | Proven by |
|---|---|---|---|---|
| T1 Never sign; the Terms gate is human-only | 1 | BLOCKER | - | S-01, S-02, S-03, X-02 |
| T2 Human confirmation guard for outward actions | 1 | BLOCKER | - | S-06 |
| T3 Secrets: keys never in logs or the repo | 1 | BLOCKER | - | S-04, P-08 |
| T4 One source of truth for principal and request; validate before any call | 2 | MAJOR | - | I-02, I-03, I-04, I-01 |
| T5 Idempotent publish: probe, then live, once | 2 | BLOCKER | T2 | P-01, P-02, P-03, P-04, P-04b, X-01 |
| T6 Payload shape and content | 2 | BLOCKER | T5 | P-05, P-06, P-07, P-10, P-11 |
| T7 Keys: poll with the answer_key; stop if one is required and missing | 2 | BLOCKER | T5 | L-01, P-09 |
| T8 Polling that reports changes and survives contradictions | 3 | MAJOR | T7 | L-02, L-03, L-04, L-05, L-06, L-07, L-08, L-09, X-03, X-01 |
| T9 Join only after acceptance, once, with honest messages | 3 | MAJOR | T2, T8 | J-01, J-02, J-03, J-04 |
| T10 Closing report to the principal | 3 | MAJOR | T8 | R-01, R-02, R-03 |
| T11 Fail loudly; report missing inputs as such | 3 | MAJOR | - | T-01, X-04, X-04b |
| T12 Wire the tests into CI | 4 | MINOR | - | T-03 (manual), T-04 (manual) |

### T1 Never sign; the Terms gate is human-only

Priority 1, BLOCKER. Depends on: nothing.
Findings: F01.

Change:

- Remove every call to a signing endpoint from the automated flow (`/api/nda/sign` and similar).
- If signing is ever needed, put it in a module named `*human*` or `*principal*` that requires a token only the principal holds; the agent cannot import it.
- When the gate is `pending`, print `ACTION_FOR_PRINCIPAL:` naming the document and the platform URL.
- When the gate is `confirmed` but no supervisor is bound, print `WARN GATE_NO_SUPERVISOR`, treat the Terms as NOT signed and do not call matching.

Done when these pass: `S-01`, `S-02`, `S-03`, `X-02`

### T2 Human confirmation guard for outward actions

Priority 1, BLOCKER. Depends on: nothing.
Findings: F02.

Change:

- Live publish and join run only when `CAPE_CONFIRM=1` (or an equivalent explicit flag).
- Without it: probe only, print `INFO probe passed; live publish needs the principal's confirmation`.
- The check must be an `if` on the flag in the code path that POSTs (static check S-06).

Done when these pass: `S-06`

### T3 Secrets: keys never in logs or the repo

Priority 1, BLOCKER. Depends on: nothing.
Findings: F04.

Change:

- Route all output through one function that redacts known secrets.
- Store the answer_key only in the single state file (`CAPE_STATE_FILE`).
- Add `.env`, the state file and `*.key` to `.gitignore`.

Done when these pass: `S-04`, `P-08`

### T4 One source of truth for principal and request; validate before any call

Priority 2, MAJOR. Depends on: nothing.
Findings: F10.

Change:

- Read principal, company, contact email, agent name and request facts from one config (`CAPE_CONFIG`). No literals in code.
- Missing or empty field: `ERROR CONFIG_INVALID` and exit non-zero before any request.
- A configured delegate is written into the manifest identity and workspace.

Done when these pass: `I-02`, `I-03`, `I-04`
Static: `I-01`

### T5 Idempotent publish: probe, then live, once

Priority 2, BLOCKER. Depends on: T2.
Findings: F02, F12.

Change:

- Run a probe of the exact body; publish live only after a PASS of the identical body.
- Persist msgid (and answer_key) after the first live publish; on later runs poll that thread and do not publish again.
- A second record needs `CAPE_NEW_REQUEST=1` plus `CAPE_NEW_REASON`; otherwise `ERROR NEW_REQUEST_NEEDS_REASON`.
- A probe receipt is never stored as a thread, even if it carries a msgid.

Done when these pass: `P-01`, `P-02`, `P-03`, `P-04`, `P-04b`, `X-01`

### T6 Payload shape and content

Priority 2, BLOCKER. Depends on: T5.
Findings: F03, F05, F14.

Change:

- Nest the mandate: `manifest.mandate.intents[]`; never a top-level `mandate`.
- Build the scope from the probe's `required_by_service`, not from the SPEC; if they differ print `WARN SPEC_PROBE_MISMATCH`.
- Send all six labelled fields, none empty, including an `interface` line that names a polling schedule or endpoint.
- Do not invent geography; print `QUESTION location:` when none is configured.

Done when these pass: `P-05`, `P-06`, `P-07`, `P-10`, `P-11`

### T7 Keys: poll with the answer_key; stop if one is required and missing

Priority 2, BLOCKER. Depends on: T5.
Findings: F06.

Change:

- Poll with the answer_key whenever one was issued.
- If the thread says to use the answer_key and none was issued: `ERROR ANSWER_KEY_MISSING`, exit non-zero, no join.

Done when these pass: `L-01`, `P-09`

### T8 Polling that reports changes and survives contradictions

Priority 3, MAJOR. Depends on: T7.
Findings: F07, F08.

Change:

- Fetch the full thread each poll (no `since`); diff by message id; print `NEW id=.. kind=.. created=<UTC>` once per message.
- Print `CHANGE field: old -> new` for tier, handshake, tos and status; `NOCHANGE` otherwise.
- Normalise every timestamp to UTC.
- If publish and thread disagree on scope: `WARN STATE_MISMATCH`, do not republish.
- If a message links to another thread: `WARN STALE_LINK`, do not follow, infer no state.
- Back off and stop after `CAPE_STOP_AFTER_EMPTY` quiet polls.
- Print `CANONICAL msgid=` for the thread treated as the request.

Done when these pass: `L-02`, `L-03`, `L-04`, `L-05`, `L-06`, `L-07`, `L-08`, `L-09`, `X-03`, `X-01`

### T9 Join only after acceptance, once, with honest messages

Priority 3, MAJOR. Depends on: T2, T8.
Findings: F09.

Change:

- Join only when the polled thread shows handshake `accepted`.
- Persist the workspace uuid; a second run does not join again.
- If no delegate was disclosed: `WARN JOIN_NOT_INHERITING`.
- If the response says the principal is not bound: `ACTION_FOR_PRINCIPAL:` explaining they are bound only when they sign the Terms.

Done when these pass: `J-01`, `J-02`, `J-03`, `J-04`

### T10 Closing report to the principal

Priority 3, MAJOR. Depends on: T8.
Findings: F07.

Change:

- End every run with `SUMMARY:` (platform URL, the six fields, msgid, status, a line that any Terms is signed by the principal) and exactly one `NEXT_ACTION:` line.
- Status wording must say `accepted, not yet classified` until the thread shows a classified scope; never "matched" or "served" without evidence.

Done when these pass: `R-01`, `R-02`, `R-03`

### T11 Fail loudly; report missing inputs as such

Priority 3, MAJOR. Depends on: nothing.
Findings: F11, F13.

Change:

- Exchange unreachable: `ERROR UNREACHABLE`, exit non-zero, no fallback to another route.
- A 404 "needs sector" is `ERROR API_PREREQUISITE`, not "no match"; with a sector, state the count (`INFO matches=N`).

Done when these pass: `T-01`, `X-04`, `X-04b`

### T12 Wire the tests into CI

Priority 4, MINOR. Depends on: nothing.
Findings: -.

Change:

- Run `make selftest`, `make conformance AGENT="<your command>"` and `make static REPO=<path>` on every PR.
- Write the run order in the README: probe, publish, poll, join, human signs.

Done when these pass: see below
Manual: `T-03`, `T-04` (see `docs/test-book.md`)

## Findings these tasks answer

| Id | Severity | What | Source |
|---|---|---|---|
| F01 | BLOCKER | An agent requested a signature of the Terms/NDA; the gate flipped to "confirmed" about a minute later with no supervisor and no email on record. | P:Signature request, P:Approval email |
| F02 | BLOCKER | The same request was published three times (records 737, 745, 750) for one need. | H16, H24, H25 |
| F03 | BLOCKER | A top-level `mandate` was sent; the exchange reads it only when nested under `manifest`. Scope came back UNDECIDED. | H6, H15 |
| F04 | BLOCKER | The answer key was printed in plaintext in a log. | P:header |
| F05 | MAJOR | Spec and probe disagree on the required scope (`sector` vs `capability`). | H5, H17 |
| F06 | MAJOR | The receipt gave no usable answer_key (null) while the thread said the msgid is weak. | H12, H20, P4 |
| F07 | MAJOR | Publish said scope bucket None/SERVED; the thread said UNDECIDED / "no mandate declared". | H18, H21, P6 |
| F08 | MAJOR | A delta poll with an empty delta said "No answer yet"; duplicate notices and a nudge with a wrong timestamp and link appeared. | P5, H23, H36 |
| F09 | MAJOR | Join with "acting as delegate" in the name did not delegate; the manifest must disclose the delegate. The principal is bound only at the human gate. | H28, P:Workspace join |
| F10 | MAJOR | Principal, company and contact differ between the two runs; no single source of truth. | H:header, P:header |
| F11 | MAJOR | The connector is read-only and the skill names a tool that was absent; the agent fell back to a raw POST. | H1, H2, H3, P1 |
| F12 | MAJOR | A probe returned a msgid and a PASS that looks like a filed request. | P3, H8 |
| F13 | MAJOR | The matches endpoint returned 404 "needs sector" with an empty sector; the agent had no input for it. | P:Match check |
| F14 | MINOR | Geography (France) was assumed by the agent, not asked. | P11 |

## For Cape, not for the agent

Do not work around these in the agent; they are defects on the exchange side to raise with Cape.

- SPEC says consultant_search requires `sector`; the probe and publish require `capability`.
- The SPEC example nests `mandate` under `manifest` but calls it an optional sibling.
- Publish reports scope bucket None/SERVED while the thread reports UNDECIDED and "no mandate declared".
- A probe returns a msgid and a PASS that resemble a filed request.
- The Terms document is never attached to the thread; the gate can flip to confirmed with no human supervisor and no email event after an agent request.
- A delta poll with nothing new says "No answer yet" instead of "No new messages".
- Nudge 641: timestamp earlier than the poll, link points at another msgid, "handshake completed" after it was already accepted.
- /api/matches and /api/deal-flow return 404 with an empty sector although empty is documented as "no filter".
- No project-manager service type in the catalog; consultant_search is the closest.
- The entity_binding prerequisite asks to name a principal who was already named.
