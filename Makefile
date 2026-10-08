.PHONY: run test contract conformance static selftest all fmt

PORT ?= 8090

run:            ## start the test server
	python3 server.py --port $(PORT)

test:           ## run the sample test book against a bundled server (auto-starts it)
	python3 testbook.py --serve tests/sample_test_book.json

test-live:      ## run the sample book against the LIVE exchange (READ THE BOOK FIRST: it writes)
	python3 testbook.py --base https://www.capepartners.fr tests/sample_test_book.json

contract:       ## the mock reproduces the behaviours seen in the live sessions
	python3 testbook.py --serve tests/contract_book.json

AGENT ?= python3 agents/reference_agent.py
REPO  ?= agents

conformance:    ## run AGENT against the test server (default: the reference agent)
	python3 agent_conformance.py --agent "$(AGENT)"

static:         ## read-only source checks on REPO
	python3 static_checks.py $(REPO)

selftest:       ## the tests must pass the reference agent AND fail the naive one
	python3 testbook.py --serve tests/sample_test_book.json tests/contract_book.json
	python3 agent_conformance.py --agent "python3 agents/reference_agent.py" --strict
	! python3 agent_conformance.py --agent "python3 agents/naive_agent.py"

all: test contract conformance
