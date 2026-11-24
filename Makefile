PY ?= .venv/bin/python

.PHONY: setup fixtures test run eval eval-regressed demo serve clean

setup:            ## venv, python deps, and the local OCR helper
	python3 -m venv .venv
	.venv/bin/pip install -q -r requirements.txt
	cd ocr && npm install --no-audit --no-fund

fixtures:         ## regenerate the synthetic PDFs (committed, so optional)
	$(PY) scripts/make_fixtures.py

test:
	$(PY) -m pytest -q

run:
	$(PY) -m crev run

eval:
	$(PY) -m crev eval

eval-regressed:   ## same eval with the regressed chunker policy; exits 1
	$(PY) -m crev eval --chunker v2

demo: run eval    ## review the file, build out/report.html, score it
	@echo "open out/report.html, or run: make serve"

serve:
	$(PY) -m crev serve

clean:
	rm -rf out .cache .pytest_cache
