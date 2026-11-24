import json
import threading
import urllib.error
import urllib.request
from decimal import Decimal

import pytest

from crev import audit, checks, evals, ocr, pipeline, report
from crev.model import Chunk, Corpus, DocInfo
from crev.providers import LLMProvider

needs_ocr = pytest.mark.skipif(ocr.engine_name() == "none", reason="no OCR engine installed (make setup)")


@pytest.fixture(scope="module")
def run():
    return pipeline.run()


@pytest.fixture(scope="module")
def run_v2():
    return pipeline.run(chunker="v2")


def corpus_of(doc, kind, text, page=1):
    info = DocInfo(doc, doc + ".pdf", 1, [Chunk(f"{doc}:p{page}:c0", doc, page, kind, text)])
    return Corpus({doc: info}, "test", "none")


# --- units and checks -------------------------------------------------------------------------

def test_unit_normalisation():
    assert checks.parse_quantity("0.25 GOhm")[0] == checks.parse_quantity("250 MOhm")[0]
    assert checks.parse_quantity("0.62 mA")[0] == Decimal("0.00062")
    assert checks.parse_quantity("230 V AC")[1] == "volt"
    assert checks.parse_quantity("2.5 A", "volt") is None


def test_limit_ignores_the_pass_cell():
    table = "Test | Measured | Unit | Requirement | Result\nTouch current, fault | 0.62 | mA | <= 0.5 mA | Pass"
    req = {"id": "R", "text": "t", "doc": "d", "row": "^touch current", "op": "<=", "limit": "0.5 mA"}
    res = checks.limit(req, corpus_of("d", "table", table))
    assert res.verdict == "not_met" and "0.62" in res.evidence[0].quote


def test_limit_converts_units():
    table = "Insulation resistance | 0.25 | GOhm | >= 100 MOhm | Pass"
    req = {"id": "R", "text": "t", "doc": "d", "row": "^insulation", "op": ">=", "limit": "100 MOhm"}
    assert checks.limit(req, corpus_of("d", "table", table)).verdict == "met"


def test_limit_wrong_unit_family_is_flagged_not_guessed():
    req = {"id": "R", "text": "t", "doc": "d", "row": "^touch", "op": "<=", "limit": "0.5 mA"}
    res = checks.limit(req, corpus_of("d", "table", "Touch current | 0.3 | V | <= 0.5 mA"))
    assert res.verdict == "insufficient" and "UNIT_UNRESOLVED" in res.diagnostics


def test_consistency_detects_mismatch():
    c = corpus_of("a", "text", "Rated frequency: 60 Hz")
    c.docs["b"] = DocInfo("b", "b.pdf", 1, [Chunk("b:p1:c0", "b", 1, "text", "Rated frequency: 50 Hz")])
    req = {"id": "R", "text": "t", "sources": [{"doc": "a", "label": "rated frequency", "family": "hertz"},
                                               {"doc": "b", "label": "rated frequency", "family": "hertz"}]}
    assert checks.consistency(req, c).verdict == "not_met"


# --- ingestion --------------------------------------------------------------------------------

def test_page_numbers_match_the_pdf_footer():
    corpus = pipeline.load_corpus(pipeline.DATA / "techfile")
    for info in corpus.docs.values():
        for ch in info.chunks:
            if "Page " in ch.text and " of " in ch.text:
                assert f"Page {ch.page} of" in ch.text


def test_tables_keep_row_structure():
    corpus = pipeline.load_corpus(pipeline.DATA / "techfile")
    table = next(c for c in corpus.chunks("test_report") if c.page == 9 and c.kind == "table")
    assert "Touch current, single fault condition | 0.62 | mA" in table.text


@needs_ocr
def test_scanned_page_goes_through_ocr():
    corpus = pipeline.load_corpus(pipeline.DATA / "techfile")
    assert corpus.docs["test_report"].ocr_pages == [11]
    ocr_chunk = next(c for c in corpus.chunks("test_report") if c.kind == "ocr")
    assert "230 V" in ocr_chunk.text


# --- end to end against the gold set ----------------------------------------------------------

def test_every_citation_is_verbatim(run):
    corpus = pipeline.load_corpus(pipeline.DATA / "techfile")
    for r in run["results"]:
        assert "CITATION_INVALID" not in r["diagnostics"]
        for e in r["evidence"]:
            assert " ".join(e["quote"].split()).lower() in " ".join(corpus.by_id(e["chunk_id"]).text.split()).lower()


def test_gold_set_passes(run):
    ev = evals.evaluate(run)
    skip = {"REQ-2.3"} if ocr.engine_name() == "none" else set()
    failing = [x["id"] for x in ev["rows"] if not x["passed"] and x["id"] not in skip]
    assert failing == []
    assert ev["not_met"]["recall"] == 1.0 or skip


def test_baseline_has_no_regressions(run):
    base = evals.load_baseline()
    if ocr.engine_name() == "none":
        pytest.skip("baseline recorded with OCR")
    assert evals.compare(evals.evaluate(run), base)["ok"]


def test_chunker_v2_regression_is_caught(run_v2):
    ev = evals.evaluate(run_v2)
    cmp = evals.compare(ev, evals.load_baseline())
    assert not cmp["ok"]
    assert {"REQ-3.3", "REQ-5.3"} <= set(cmp["broken"])
    assert ev["categories"].get("missed_table_value", 0) >= 4
    assert ev["categories"].get("wrong_page", 0) >= 1
    assert ev["not_met"]["recall"] < 1.0


def test_unknown_chunker_rejected():
    with pytest.raises(ValueError):
        pipeline.run(chunker="v9")


# --- providers --------------------------------------------------------------------------------

REQ = {"id": "R", "text": "Electric shock is assessed.", "docs": ["risk_assessment"], "retrieve": ["electric shock"]}


def llm_run(answer, tmp_path):
    prov = LLMProvider(post=lambda payload: answer)
    reqs = tmp_path / "r.yaml"
    reqs.write_text("requirements:\n  - {id: R, text: x, kind: semantic, docs: [risk_assessment], retrieve: ['electric shock']}\n")
    return pipeline.run(reqs_path=reqs, provider=prov)["results"][0]


def test_llm_answer_with_real_quote_is_accepted(tmp_path):
    ans = '{"verdict": "met", "passage": 0, "quote": "Electric shock from accessible live parts", "rationale": "ok"}'
    r = llm_run(ans, tmp_path)
    assert r["verdict"] == "met" and r["evidence"][0]["page"] == 4


def test_llm_fabricated_quote_is_downgraded(tmp_path):
    ans = '{"verdict": "met", "passage": 0, "quote": "Residual risk is negligible", "rationale": "ok"}'
    r = llm_run(ans, tmp_path)
    assert r["verdict"] == "insufficient" and "CITATION_INVALID" in r["diagnostics"]


def test_llm_garbage_is_insufficient(tmp_path):
    assert llm_run("I think it is fine.", tmp_path)["verdict"] == "insufficient"


def test_llm_provider_needs_configuration(monkeypatch):
    monkeypatch.delenv("CR_LLM_URL", raising=False)
    with pytest.raises(RuntimeError):
        LLMProvider()


# --- audit log and report ---------------------------------------------------------------------

def test_audit_chain_and_tamper_detection(run, tmp_path):
    p = tmp_path / "audit.jsonl"
    audit.append(p, run, "REQ-2.2", "accept", "rev")
    audit.append(p, run, "REQ-3.3", "override", "rev", "met", "lab confirmed re-test")
    assert audit.verify(p) == (True, None)
    lines = p.read_text().splitlines()
    first = json.loads(lines[0])
    first["final_verdict"] = "met"
    p.write_text(json.dumps(first) + "\n" + lines[1] + "\n")
    assert audit.verify(p) == (False, 0)


def test_audit_validation(run, tmp_path):
    p = tmp_path / "a.jsonl"
    with pytest.raises(ValueError):
        audit.append(p, run, "REQ-3.3", "override", "rev", "met", "")
    with pytest.raises(ValueError):
        audit.append(p, run, "NOPE", "accept")
    assert not p.exists()


def test_report_links_pages_and_server_writes_audit(run, tmp_path):
    report.build(run, tmp_path, pipeline.DATA / "techfile")
    html = (tmp_path / "report.html").read_text()
    assert all(r["req_id"] in html for r in run["results"]) and "#page=" in html
    srv = report.serve(tmp_path, 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://localhost:{srv.server_address[1]}"
    try:
        def post(body):
            req = urllib.request.Request(base + "/api/review", json.dumps(body).encode(), {"Content-Type": "application/json"})
            return urllib.request.urlopen(req)
        assert post({"req_id": "REQ-2.2", "decision": "accept", "reviewer": "r"}).status == 200
        with pytest.raises(urllib.error.HTTPError) as e:
            post({"req_id": "REQ-2.2", "decision": "override", "final_verdict": "met", "note": ""})
        assert e.value.code == 400
        assert urllib.request.urlopen(base + "/").status == 200
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/../crev/cli.py")
    finally:
        srv.shutdown()
        srv.server_close()
    entries = audit.read(tmp_path / "audit.jsonl")
    assert len(entries) == 1 and entries[0]["req_id"] == "REQ-2.2" and audit.verify(tmp_path / "audit.jsonl")[0]
