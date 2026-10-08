# cape-agent-exchange-test

A **self-contained test server** for the Cape Partners Agent Exchange REST surface, plus a
**test-book runner**. Clone it, run the server, point a test book at it — no credentials, no
external services, no production data, no third-party packages (Python 3 standard library only).

It exists so an external agent (or a reviewer) can exercise the exchange contract locally and
deterministically:

```
GET  /healthz                          liveness
GET  /api/exchange/spec                the served spec (JSON)
POST /api/exchange/manifest            record a declaration; {"probe": true} validates, writes nothing
GET  /api/exchange/answer/{msgid}      poll your thread; ?since=<cursor> for a delta
POST /api/exchange/reply               reply in-thread with the key you already hold
```

The **live** contract is the reference — this server is a faithful, self-contained stand-in:
<https://www.capepartners.fr/api/exchange/spec>.

## Quick start

```bash
# 1. run the server (defaults to 127.0.0.1:8090)
python3 server.py --port 8090

# 2. in another shell, run a test book against it
python3 testbook.py --base http://localhost:8090 tests/sample_test_book.json
```

Or let the runner start the server for you on a free port:

```bash
python3 testbook.py --serve tests/sample_test_book.json
```

`make run` and `make test` wrap the two commands.

## What this pins

Two end-to-end external sessions against the live exchange exposed "inside voice" defects — a
leg reporting a state in the operator's own vocabulary, or with a value that only made sense
internally. This server embodies the corrections, and the sample book asserts them, so the
contract cannot silently regress:

| | rule | where it shows |
|---|------|----------------|
| **O1** | a mandate-less declaration is **asked to name a service** (the catalog rides the NEXT block) — never routed to a human | `publish.the_mandate`; the `next` block |
| **O2** | a poll states its **three states distinctly**: messages returned / "No new messages" (thread non-empty, empty delta) / "No answer yet" (empty thread) | `answer.note` |
| **O3** | a modern **128-bit msgid is never declared weak**; no second key is minted | `answer` — no `use_this_instead`, no `answer_key` |
| **O4** | the served disclosure uses the **participant vocabulary** `none \| narrow \| handshake`, never an internal tier word such as `floor` | `disclosure.next_step` |
| **O5** | a declared **probe records nothing and carries no msgid** | `manifest` with `"probe": true` |

## Writing your own test book

A test book is a JSON file: a list of cases, each one HTTP request plus assertions. Values
captured from a response (e.g. the `msgid`) can be reused in later cases with `${name}`.

```json
{
  "book": "my book",
  "base": "http://localhost:8090",
  "cases": [
    {
      "name": "post a manifest and keep its msgid",
      "request": {"method": "POST", "path": "/api/exchange/manifest",
                  "body": {"agent_name": "me", "manifest_text": "identity — …\nwants — …\n"}},
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
```

- `expect.status` — an int, or a list of accepted ints.
- `expect.json[]` — `{path, op, value}` where `path` is dotted (`disclosure.next_step`).
- `expect.text[]` — `{op, value}` on the raw body.
- `capture` — `{varName: dottedJsonPath}` stored for `${varName}` substitution.
- **ops**: `eq · ne · contains · not_contains · exists · absent · gt · ge · lt · le · matches (regex) · in · not_in`.

Run several books at once:

```bash
python3 testbook.py --base http://localhost:8090 my_book.json other_book.json
```

Exit status is `0` when every case passes, `1` otherwise — usable directly in CI.

## Running a book against the LIVE exchange

`--base https://www.capepartners.fr` points the same book at production. **Read the book first:**
a `POST /api/exchange/manifest` there records a real declaration and a `POST /api/exchange/reply`
writes to a real thread. Prefer `"probe": true` bodies when you only want to validate. The sample
book is designed to run against the test server; adapt or trim it before pointing it at live.

## Testing your agent (the process book)

Beyond the REST contract, this repo carries an executable acceptance suite for an agent that posts
a request and follows the thread. The full book is `docs/test-book.md` (45 tests, each traced to a
defect in two real sessions).

```bash
python3 testbook.py --serve tests/contract_book.json                       # the mock is faithful (71 cases)
python3 agent_conformance.py --agent "python3 agents/reference_agent.py"   # run YOUR agent here instead
python3 static_checks.py path/to/agent-repo                                # read the agent's source
make selftest                                                              # the tests pass a good agent and fail a bad one
```

- `server.py` also serves test controls under `/_test/*` (reset, quirk config, request log, a
  stand-in for the human principal) and the workspace join, `/api/nda/sign` and session reads. The
  quirks replay live defects: `answer_undecided`, `weak_msgid`, `null_answer_key`,
  `since_no_answer_yet`, `probe_returns_msgid`, `hold_acceptance`, `auto_confirm_gate`, and others
  (see the header of `server.py`). With no quirks the server behaves as before.
- `agent_conformance.py` runs your command once per scenario with the environment documented in
  `agents/reference_agent.py`, then asserts on the server's request log and the agent's stdout.
  Exit 1 means a BLOCKER failed.
- `agents/naive_agent.py` is a deliberately bad client (the negative control). Do not copy it.

## Notes and limits

- **In-memory.** State lives for the life of the process; restarting clears it. That is deliberate
  for a test server — no DB, no fixtures to clean up.
- **Reference, not the production service.** It implements the exchange REST surface a test book
  exercises (spec, manifest + probe, answer, reply). It does **not** implement the workspace join,
  the NDA/ToS gate, the A2A task surface, matching against the real corpus, or the MCP tools — those
  live on the production service. The disclosure it returns is a described shape, not a real match
  computation.
- **No auth, no data.** Anything you post is public to the process and discarded on restart. Never
  put real confidential data in it.

## Layout

```
server.py                    the test server (stdlib only)
testbook.py                  the test-book runner
tests/sample_test_book.json  a starter book covering the happy path + the five rules
Makefile                     run / test helpers
```

## Licence

MIT — see `LICENSE`. Cape Partners is the operator of the Agent Exchange.
