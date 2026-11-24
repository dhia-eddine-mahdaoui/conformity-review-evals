# Conformity review with source citations and regression evals

A small, finished prototype of an AI-assisted review of a technical file against a requirements
checklist, built around two ideas:

1. **Every verdict carries a verbatim quote and a page link**, and a quote that cannot be found in the
   cited source text is rejected automatically.
2. **Evals that catch regressions and say why.** A gold set, a baseline, per-requirement pass/fail,
   precision/recall on "not met", and a failure-category breakdown. A deliberately introduced chunker
   regression shows the eval failing for the right reasons (below).

Everything runs offline with a deterministic backend. An LLM can be plugged in behind the same provider
interface through environment variables; no keys are stored anywhere.

All documents, names and standards in this repo are fictional ("Acme Widgets Ltd", "Example Test
Laboratory", "EXS 1000-1"). Numbers in this README come from runs of the code in this repo.

## The problem

A conformity file is hundreds of pages across test reports, declarations, risk assessments, scanned
annexes and tables. A reviewer must check it against a checklist: do the declared ratings match the
test report, is every measured value within its limit, is every high risk closed out? A system is only
useful if the reviewer can trust it, which means: show the exact source, never invent evidence, say
"insufficient evidence" instead of guessing, keep an audit trail, and have tests that notice when a
change quietly makes it worse.

The demo file is small (28 pages in 3 PDFs) but contains the traps that matter:

| Planted trap | Where | Expected outcome |
|---|---|---|
| Declared frequency 60 Hz, test report 50 Hz | declaration p1 / report p3 | REQ-2.2 not met |
| Touch current 0.62 mA over a 0.5 mA limit, but the lab wrote "Pass" | report p9 (table) | REQ-3.3 not met |
| Insulation resistance in GOhm, limit in MOhm | report p7 (table) | REQ-3.1 met after unit conversion |
| Rated current only legible on a scanned nameplate | report p11 (image only) | REQ-2.3 needs OCR |
| Hazard with High residual risk and verification "Pending" | risk assessment p5 | REQ-5.3 not met |
| No laboratory accreditation number anywhere | report | REQ-6.1 insufficient evidence |

## Architecture

```
 data/techfile/*.pdf                         data/requirements.yaml (15 clauses)
        |                                               |
        v                                               |
 ingest.py  text blocks + ruled tables (pymupdf)        |
        |   page with < 24 chars of text and an image   |
        |        --> ocr.py (tesseract CLI | tesseract.js | none)
        v                                               |
 chunkers.py  v1: paragraph / table / OCR page chunks   |
        |     each chunk keeps doc, page, kind, bbox    |
        v                                               v
 +------------------------------------------------------------+
 | pipeline.py: one check per requirement (checks.py)         |
 |   consistency      same value across documents (units SI)  |
 |   limit            every table row vs a limit, recomputed  |
 |   evidence_present required statements exist               |
 |   risk_table       High residual risk must be verified     |
 |   semantic  --->   provider interface (providers.py)       |
 |                      heuristic (offline default) | llm     |
 +------------------------------------------------------------+
        |   validate_citations: quote must occur verbatim in the cited chunk,
        |   else verdict is downgraded to "insufficient" (CITATION_INVALID)
        v
 results.json --> report.py: out/report.html (verdict, quote, #page link,
        |                    accept/override form)
        |                         |
        |                         v  POST /api/review (local server)
        |                    out/audit.jsonl  (hash-chained JSON lines)
        v
 evals.py: gold.yaml + baseline.json --> pass/fail, P/R on "not met",
           failure categories, regression diff, exit code
```

Verdicts are `met`, `not_met`, `insufficient`. "Insufficient" means no usable evidence was found; it is
the fail-safe answer whenever a check cannot find or parse what it needs.

## Run it

Requirements: Python 3.10+, and optionally node (for OCR) or the `tesseract` binary.

```
make setup     # venv, python deps, npm install of the OCR helper (tesseract.js, English data included)
make test      # 20 tests, about 6 s
make demo      # review the file, write out/report.html, run the eval
make serve     # http://localhost:8765/ : reviewer accept/override writes out/audit.jsonl
make eval-regressed   # the regression demo, exits 1
```

Without any OCR engine everything still runs; REQ-2.3 then comes back `insufficient` with diagnostic
`OCR_UNAVAILABLE` and the eval reports it as an `ocr_error` (14/15, see below).

Optional LLM for the `semantic` requirements (REQ-5.1, REQ-5.2), any OpenAI-compatible chat endpoint:

```
CR_LLM_URL=... CR_LLM_MODEL=... CR_LLM_KEY=... python -m crev run --provider llm
```

The model is shown only retrieved passages, must answer in JSON, and its quote is checked against the
source text like any other. This path is covered by unit tests with a stubbed transport (accepted
quote, fabricated quote downgraded, unparsable answer); it has not been run against a live endpoint.

## Reviewer output and audit log

`out/report.html` is one page: requirement, verdict badge, evidence quote(s) with a link to
`techfile/<doc>.pdf#page=N`, the rationale, diagnostics, and an Accept / Override form. The local
server (localhost only) appends each decision to `out/audit.jsonl`: timestamp, run id, requirement,
system verdict, decision, final verdict, reviewer, note, cited pages. An override requires a verdict and
a note. Each line stores the hash of the previous one; `python -m crev audit` verifies the chain and
the tests show an edited line is detected. This is tamper-evident, not tamper-proof.

## Eval results (baseline, `make eval`)

Provider `heuristic`, chunker `v1`, OCR `tesseract-js`, 104 chunks over 28 pages.

| Requirement | Expected | Got | Cited pages correct | Result |
|---|---|---|---|---|
| REQ-1.1 manufacturer name and address | met | met | yes | PASS |
| REQ-1.2 model identical across 3 documents | met | met | yes | PASS |
| REQ-2.1 rated voltage matches | met | met | yes | PASS |
| REQ-2.2 rated frequency matches | not met | not met | yes | PASS |
| REQ-2.3 nameplate current (OCR) matches | met | met | yes | PASS |
| REQ-3.1 insulation resistance (unit conversion) | met | met | yes | PASS |
| REQ-3.2 dielectric strength | met | met | yes | PASS |
| REQ-3.3 touch current limit | not met | not met | yes | PASS |
| REQ-3.4 temperature rise | met | met | yes | PASS |
| REQ-4.1 standard cited | met | met | yes | PASS |
| REQ-4.2 signed and dated | met | met | yes | PASS |
| REQ-5.1 electric shock assessed | met | met | yes | PASS |
| REQ-5.2 overheating assessed | met | met | yes | PASS |
| REQ-5.3 High residual risks verified | not met | not met | yes | PASS |
| REQ-6.1 accreditation number | insufficient | insufficient | n/a | PASS |

15/15 passed; verdict accuracy 1.00; page accuracy 1.00; "not met": precision 1.00, recall 1.00
(3 true positives, 0 false positives, 0 false negatives).

**Read this number honestly.** The fixtures, the checks and the gold labels were all written by the same
person for this demo, so 15/15 is a sanity check that the pipeline does what it was designed to do. It is
not an accuracy estimate for real files. The value of the harness is in what it does when something
changes.

The eval is also useful when the environment changes: with `--ocr none` the same run gives 14/15, the
single failure categorised `ocr_error` (diagnostic `OCR_UNAVAILABLE`), and exit code 1 against the
baseline. With OCR on, the engine mis-read one line of the noisy nameplate scan ("OUTPUT: 24 V DC"
came back as "QUTRPUT > 24.N DC"); no requirement depends on that line, so it passes, but it is the kind
of error the OCR category exists for.

## The regression story

`chunkers.py` has two policies. `v1` (default) keeps one chunk per paragraph, table or OCR page. `v2`
is a plausible "efficiency" refactor: merge neighbouring chunks into windows of up to 1200 characters
and flatten tables to a single line so they read like prose. Chunk count drops from 104 to 15, which
looks like a win in a diff.

It is committed on a branch so the repo history shows it: tag `v1.0-baseline` is the good state, tag
`v1.1-regressed` flips the default to `v2` and nothing else.

```
git diff v1.0-baseline v1.1-regressed        # a one-line change
git checkout v1.1-regressed && make eval     # exit code 1
# or, without checking anything out:
python -m crev eval --chunker v2
```

Result on the same inputs:

| | baseline (v1) | regressed (v2) |
|---|---|---|
| requirements passed | 15/15 | 6/15 |
| verdict accuracy | 1.00 | 0.60 |
| page accuracy | 1.00 | 0.40 |
| "not met" recall | 1.00 | 0.33 |
| "not met" precision | 1.00 | 1.00 |
| failure categories | none | missed_table_value 6, wrong_page 3 |

The eval prints which requirements broke relative to the baseline (REQ-1.2, 3.1, 3.2, 3.3, 3.4, 4.1,
5.1, 5.2, 5.3) and exits non-zero, so a CI gate would have stopped the change.

### Why it failed

The per-requirement diagnostics point at two separate causes, not one:

1. **Tables lost their row structure** (6 requirements: REQ-3.1, 3.3, 3.4, 5.1, 5.2, 5.3). Flattening
   puts a whole table on one line. The row matchers anchor on the first cell of a line (`^touch
   current`), find no row (`NO_ROW`) or no outcome (`NO_OUTCOME`), and fall back to
   `insufficient`. Two of the six are real defects in the file (touch current over the limit,
   High-risk hazard unverified) which now read as "insufficient evidence" instead of "not met". That
   is the safe direction (no false "met"), but it is why recall on "not met" falls from 1.00 to 0.33
   while precision stays 1.00: a reviewer skimming for red items would miss them.
2. **Page identity was lost** (REQ-3.2, 4.1, 1.2). A merged window is labelled with the page of its
   first chunk, so text from page 2 is cited as page 1 and the dielectric strength row from page 8 is
   cited as page 7. The verdicts are right but the page link sends the reviewer to the wrong place,
   which is exactly the failure a citation-based system must not hide. REQ-1.2 shows a quieter variant:
   with the page-3 table flattened, the model-number check silently fell through to the OCR nameplate
   (page 11). Same value, different source.

What the failure categories do and do not tell you: they are derived from the gold tags and the
diagnostic codes, so they say where to look, not what the root cause is. Here the category
`missed_table_value` plus `NO_ROW` was enough to get to the flattening in one step; the page failures
needed the cited-versus-expected page columns.

Fix: chunks never span pages and tables stay row-structured. The eval is the guard that keeps that
true.

## Which parts come from earlier work

The page-reading approach comes from an earlier PDF review project of mine (source-linked extraction of
figures from reports): read the text layer first and OCR only pages with fewer than 24 characters,
English tesseract.js with a local language file (`ocr/eng.traineddata.gz`, Apache-2.0 licensed tesseract
data), evidence records that keep a page-normalised box, Decimal-based number parsing, and the idea of
reporting `conflict` / `limited` / `missing` instead of forcing an answer (here: not met / insufficient).
The code in this repo is new and adapted to the conformity setting.

## Limitations, and what I would harden next

- **Synthetic data, one author.** Fixtures, checks and gold set were made together; the fixtures use
  clean ruled tables and one noisy but straight scan. Real files bring skewed scans, borderless tables,
  tables split across pages, multi-column layouts, units written many ways, and tables inside images.
- **Heuristics are layout-aware.** Row matchers anchor on the first cell; labels are regexes written per
  requirement. A real system needs learned or configured table schemas and a test per document family.
- **OCR is a single engine with no confidence handling.** Next: per-word confidence, abstain below a
  threshold, a second engine for disagreement, and a page-image viewer with the evidence box drawn
  (the boxes are already stored for text chunks).
- **The LLM path is thin.** It is stub-tested only. Next: a labelled set where the model must abstain,
  prompt/version pinning in the run id, retrieval beyond keyword matching, and cost/latency tracking.
- **The gold set is 15 items.** Next: real redacted files, a second labeller and agreement
  measurement, per-failure-category thresholds rather than one baseline file, and CI that runs
  `make eval` and fails on regression.
- **Audit log** is a local hash chain. A production one needs signed entries, identity from the
  environment instead of a free-text name, and storage the reviewer cannot rewrite.
- **The report server** is a localhost demo with no authentication.
- **Scale.** Table detection costs about a second per table page here; a 500-page file needs
  page-level caching and parallelism, which the module layout allows but which is not implemented
  beyond an in-process memo and an OCR cache.

## Layout

```
crev/            package: ingest, ocr, chunkers, checks, providers, pipeline, evals, audit, report, cli
data/            requirements.yaml, techfile/*.pdf (generated by scripts/make_fixtures.py)
eval/            gold.yaml, baseline.json
ocr/             tesseract.js helper and English language data
tests/           pytest suite
```

Commands: `python -m crev run | eval | serve | audit`.
