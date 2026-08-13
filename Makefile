.PHONY: setup prepare-data bench-cognodb bench-neo4j_aura_free bench-all report

PYTHON ?= python3

setup:
	$(PYTHON) -m venv .venv
	. .venv/bin/activate && pip install -r requirements.txt

prepare-data:
	$(PYTHON) scripts/prepare_dataset.py --raw data/raw/netflix_titles.csv --out data/sample

bench-cognodb:
	$(PYTHON) -m src.harness.run_benchmark --platform cognodb

bench-neo4j_aura_free:
	$(PYTHON) -m src.harness.run_benchmark --platform neo4j_aura_free

bench-all: bench-cognodb bench-neo4j_aura_free

report:
	$(PYTHON) -m src.harness.report
