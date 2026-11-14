# make lab        build the host image and start Elasticsearch, the host and three shippers
# make reproduce  run the whole matrix (several hours), re-reconcile, then rebuild every table,
#                 chart and results/summary.json from the raw run files
# make results    rebuild tables, charts and summary from the committed raw files only (no lab)
# make test       lint and unit tests
UV ?= uv

.PHONY: lab run reproduce results test down clean-lab

lab:
	$(UV) sync --locked
	$(UV) run logcanary lab-up

run:
	$(UV) run logcanary matrix

reproduce: lab run
	$(UV) run logcanary reconcile
	$(MAKE) results

results:
	$(UV) run logcanary report
	$(UV) run logcanary figures
	$(UV) run logcanary summary

test:
	$(UV) run ruff check src tests
	$(UV) run pytest -q

down:
	$(UV) run logcanary lab-down

clean-lab: down
	docker volume rm -f logcanary_es-data logcanary_hostlog logcanary_fbstate
