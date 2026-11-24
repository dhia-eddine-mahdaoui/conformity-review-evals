"""The harder set: unit traps, conflicting documents, split tables, rotated scan, distractors, injection."""
from decimal import Decimal

import pytest

from crev import checks, evals, ocr, pipeline

needs_ocr = pytest.mark.skipif(ocr.engine_name() == "none", reason="no OCR engine installed (make setup)")
KNOWN_GAPS = {"HRD-2.7"}  # supply frequency written in words ("fifty hertz"); documented in the README


def hard(suite_runs):
    return next(r for c, r in suite_runs if c["name"] == "hard")


def test_suite_has_at_least_forty_items(suite_eval):
    assert suite_eval["total"] >= 40 and set(suite_eval["cases"]) == {"core", "hard"}
    tags = set(suite_eval["by_tag"])
    assert {"unit", "conflict", "split_table", "rotated_scan", "distractor", "injection", "borderless", "number_format"} <= tags


@needs_ocr
def test_hard_set_only_fails_the_documented_gap(suite_eval):
    failing = {x["id"] for x in suite_eval["rows"] if not x["passed"]}
    assert failing == KNOWN_GAPS
    assert suite_eval["categories"] == {"missed_evidence": 1}


def test_unit_parsing_covers_the_traps():
    q = checks.parse_quantity
    assert q("650 uA")[0] == q("0.65 mA")[0] == Decimal("0.00065")
    assert q("7.5 kW")[0] == q("7500 W")[0]
    assert q("0.4 kV")[0] == q("400 V")[0]
    assert q("52000 kOhm")[0] == q("52 MOhm")[0]
    assert q("68 dB(A)")[1] == "decibel" and q("93.1 %")[1] == "percent"


def test_decimal_comma_and_thousands_separator():
    assert checks.parse_quantity("0,42 mA")[0] == Decimal("0.00042")
    assert checks.parse_quantity("12,5 A")[0] == Decimal("12.5")
    assert checks.parse_quantity("1,500 V")[0] == Decimal(1500)


def test_split_table_failure_is_found_on_the_second_page(suite_runs):
    res = {x["req_id"]: x for x in hard(suite_runs)["results"]}
    r = res["HRD-3.5"]
    assert r["verdict"] == "not_met" and {e["page"] for e in r["evidence"] if e["kind"] == "table"} == {9}
    assert res["HRD-5.1"]["verdict"] == "not_met" and res["HRD-5.1"]["evidence"][0]["page"] == 4


def test_prose_distractor_does_not_override_the_results_table(suite_runs):
    r = next(x for x in hard(suite_runs)["results"] if x["req_id"] == "HRD-3.4")  # earlier prototype quoted at 5.1 mA in an annex
    assert r["verdict"] == "met" and all(e["kind"] == "table" for e in r["evidence"])


def test_instruction_inside_the_document_is_inert(suite_runs):
    res = {x["req_id"]: x for x in hard(suite_runs)["results"]}
    assert res["HRD-4.4"]["verdict"] == "insufficient" and res["HRD-4.4"]["evidence"] == []
    assert res["HRD-4.2"]["verdict"] == "insufficient"  # signed but the date is blank


def test_conflicting_documents_are_not_met(suite_runs):
    res = {x["req_id"]: x for x in hard(suite_runs)["results"]}
    for rid in ("HRD-1.2", "HRD-2.3", "HRD-2.5"):
        assert res[rid]["verdict"] == "not_met", rid
    assert res[ "HRD-2.2"]["verdict"] == "met"  # 7.5 kW vs 7500 W is not a conflict


@needs_ocr
def test_sideways_scan_is_turned_upright_before_ocr(suite_runs):
    meta = hard(suite_runs)["meta"]
    assert meta["ocr_rotated"]["test_report"].get(11) in (90, 270)
    r = next(x for x in hard(suite_runs)["results"] if x["req_id"] == "HRD-2.4")
    assert r["verdict"] == "met"


def test_ocr_quality_scores_separate_clean_from_garbled():
    assert ocr.quality("MODEL: AW-200\nRATED VOLTAGE: 230 V AC\nRATED FREQUENCY: 50 Hz\nRATED CURRENT: 2.5 A") >= ocr.GOOD_QUALITY
    assert ocr.quality("ei 3 tl 2 ~ Tt oo | 1 Bb a ee xx 8 .") < ocr.GOOD_QUALITY


def test_categories_name_the_cause_when_the_ocr_engine_is_missing():
    c = next(c for c in pipeline.load_suite() if c["name"] == "hard")
    run = pipeline.run(c["data"], c["requirements"], ocr_mode="none")
    ev = evals.evaluate(run, evals.load_gold(c["gold"]))
    cats = {x["id"]: x["category"] for x in ev["rows"] if x["category"]}
    assert cats["HRD-2.4"] == "rotation_error" and cats["HRD-3.9"] == "ocr_error"
    assert run["meta"]["ocr_failed"]["test_report"] == [11, 12, 13]
