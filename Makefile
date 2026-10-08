.PHONY: run test fmt

PORT ?= 8090

run:            ## start the test server
	python3 server.py --port $(PORT)

test:           ## run the sample test book against a bundled server (auto-starts it)
	python3 testbook.py --serve tests/sample_test_book.json

test-live:      ## run the sample book against the LIVE exchange (READ THE BOOK FIRST: it writes)
	python3 testbook.py --base https://www.capepartners.fr tests/sample_test_book.json
