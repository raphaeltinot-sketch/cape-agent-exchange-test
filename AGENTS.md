# AGENTS.md - instructions for the coding agent

You are correcting how an agent posts a request to the Cape Partners Agent Exchange and follows its
thread. This repo is the **test harness and the plan**. The agent you change lives in its own code;
you run it from here with `--agent "<command>"`.

## Read in this order

1. This file.
2. `docs/ACTION_PLAN.md` - 12 tasks, in priority order, each with the tests that prove it.
   Machine-readable twin: `docs/findings.json`. All 42 scenarios: `docs/tests-index.json`.
3. `docs/test-book.md` - the full book (45 tests) and why each exists.
4. `agents/reference_agent.py` - a compliant client you can copy patterns from. Its header documents
   the environment variables and the report protocol your agent must speak.
5. `docs/source-logs/` - the two real sessions the defects came from (redacted).

## The loop

```bash
# 1. see what fails
python agent_conformance.py --agent "<your agent command>" --json results/latest.json
python static_checks.py <path to your agent repo>

# 2. work one task at a time
python agent_conformance.py --agent "<your agent command>" --only S-01,S-02,S-03,X-02 --verbose

# 3. before you finish
python agent_conformance.py --agent "<your agent command>" --strict
python static_checks.py <path to your agent repo> --history --forbid "<client name>,<principal email domain>"
python testbook.py --serve tests/sample_test_book.json tests/contract_book.json
```

`--verbose` prints the last lines of your agent's output for each failure. The failure line says
what was expected and what the server's request log shows.

## Rules (not negotiable)

- **Never call the live exchange** while developing or testing. Everything runs against `server.py`
  on localhost, started by the harness.
- **Never sign** or call a signing endpoint for the principal. The Terms gate is human-only.
- **Do not weaken the tests.** Do not edit `tests/agent_scenarios.py`, `tests/contract_book.json` or
  the assertions in `agent_conformance.py` to get a pass. If you think a test is wrong, leave it,
  and explain in `results/notes.md`.
- A new live behaviour you discover goes in as a quirk in `server.py` plus a scenario, in its own commit.
- No keys, msgids, uuids, real emails or real company names in commits.

## Priorities

BLOCKERs first: T1 (never sign), T2 (confirmation guard), T3 (secrets), then T5 to T7
(idempotent publish, payload, keys). The suite exits 1 if any BLOCKER fails.

## When you finish

Write `results/notes.md`: the final scorecard, every static `REVIEW` item and why it is acceptable,
any test you believe is wrong, and anything you changed that the plan did not ask for.
Do not claim completion unless `agent_conformance.py --strict` prints `Verdict: ACCEPT`.

## Regenerating the plan

`docs/ACTION_PLAN.md`, `docs/findings.json` and `docs/tests-index.json` are generated:
`python tests/make_plan.py`. Edit the data in that script, not the outputs.
