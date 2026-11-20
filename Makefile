# make lab        build the host image and start Elasticsearch, the host and three shippers
# make reproduce  run the whole matrix (several hours), re-reconcile, then rebuild every table,
#                 chart and results/summary.json from the raw run files
# make results    rebuild tables and summary from the run files on disk (no lab); with only the
#                 committed compact files, charts that need raw arrivals are skipped
# make raw-hashes record SHA-256 of the raw ledgers and arrivals kept out of git
# make check-raw  verify raw files on disk against results/raw_sha256.txt
# make test       lint and unit tests
UV ?= uv

.PHONY: lab run reproduce results raw-hashes check-raw test down clean-lab

lab:
	$(UV) sync --locked
	$(UV) run logcanary lab-up

run:
	$(UV) run logcanary matrix

reproduce: lab run
	$(UV) run logcanary reconcile
	$(MAKE) results raw-hashes

results:
	$(UV) run logcanary report
	$(UV) run logcanary figures
	$(UV) run logcanary summary

raw-hashes:
	find results/runs results/discarded -name 'ledger.csv.gz' -o -name 'arrivals.csv.gz' | LC_ALL=C sort \
		| xargs sha256sum > results/raw_sha256.txt

check-raw:
	sha256sum -c --quiet results/raw_sha256.txt

test:
	$(UV) run ruff check src tests
	$(UV) run pytest -q

down:
	$(UV) run logcanary lab-down

clean-lab: down
	docker volume rm -f logcanary_es-data logcanary_hostlog logcanary_fbstate
