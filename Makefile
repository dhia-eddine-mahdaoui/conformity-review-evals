PY ?= .venv/bin/python

.PHONY: demo-gif setup setup-browser fixtures test run run-agent eval eval-regressed demo serve monitor monitor-demo screenshots clean

setup:            ## venv, python deps, and the local OCR helper
	python3 -m venv .venv
	.venv/bin/pip install -q -r requirements.txt
	cd ocr && npm install --no-audit --no-fund

setup-browser:    ## optional: playwright, for the browser test and `make screenshots` (uses an installed Chrome)
	.venv/bin/pip install -q -r requirements-dev.txt

fixtures:         ## regenerate the synthetic PDFs (committed, so optional)
	$(PY) scripts/make_fixtures.py
	$(PY) scripts/make_fixtures_hard.py

test:
	$(PY) -m pytest -q

run:
	$(PY) -m crev run

run-agent:        ## agent mode: tool-using loop, step trace in the report
	$(PY) -m crev run --mode agent

eval:             ## both cases (43 items), compared with eval/baseline.json
	$(PY) -m crev eval --html out/eval.html

eval-regressed:   ## same eval with the regressed chunker policy; exits 1
	$(PY) -m crev eval --chunker v2 --no-history

demo: run eval    ## review the file, build out/report.html, score it
	@echo "open out/report.html, or run: make serve"

serve:
	$(PY) -m crev serve

monitor:          ## render out/monitor.html from out/history.jsonl; exit 1 if the latest run alerts
	$(PY) -m crev monitor

monitor-demo:     ## record five runs (healthy, agent, OCR down, bad chunker, fixed) and render the dashboard
	rm -f out/history.jsonl
	$(PY) -m crev eval --label "baseline, pipeline"
	$(PY) -m crev eval --mode agent --label "agent, scripted policy"
	-$(PY) -m crev eval --ocr none --label "OCR engine missing"
	-$(PY) -m crev eval --chunker v2 --label "chunker v2 merge"
	$(PY) -m crev eval --label "chunker v1 restored"
	-$(PY) -m crev monitor

screenshots: monitor-demo   ## regenerate docs/screenshots (needs make setup-browser)
	$(PY) scripts/screenshots.py

clean:
	rm -rf out .cache .pytest_cache

demo-gif: monitor-demo      ## re-record docs/demo.gif (needs make setup-browser)
	$(PY) scripts/record_demo.py
