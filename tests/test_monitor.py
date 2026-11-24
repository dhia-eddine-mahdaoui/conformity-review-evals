import json

from crev import cli, evals, monitor, render


def rec(score, **kw):
    base = {"ts": "2026-01-01T00:00:00+00:00", "label": "", "run_id": "x", "mode": "pipeline", "provider": "heuristic",
            "chunker": "v1", "ocr": "tesseract-js", "passed": round(score * 43), "total": 43, "score": score,
            "verdict_accuracy": score, "page_accuracy": score, "not_met_precision": 1.0, "not_met_recall": 1.0,
            "verdicts": {"met": 27, "not_met": 12, "insufficient": 4}, "insufficient_rate": 0.09, "ocr_fallback_rate": 0.044,
            "ocr_failed": 0, "rotated_pages": 1, "citation_invalid": 0, "steps": 0, "seconds": 9.0, "categories": {},
            "broken": [], "baseline_score": 0.98}
    return {**base, **kw}


def codes(history, base=0.98):
    return [c for _, c, _ in monitor.alerts_for(history[-1], history[:-1], base)]


def test_healthy_run_has_no_alerts():
    assert codes([rec(0.98), rec(0.98)]) == []


def test_score_drop_against_baseline_is_critical():
    out = monitor.alerts_for(rec(0.88, broken=["REQ-2.3"]), [rec(0.98)], 0.98)
    assert ("critical", "EVAL_DROP") == out[0][:2] and "REGRESSION" in [c for _, c, _ in out]


def test_small_wobble_does_not_alert():
    assert codes([rec(0.98), rec(0.95)]) == []


def test_insufficient_spike_and_ocr_and_citations():
    hist = [rec(0.98), rec(0.98), rec(0.98, insufficient_rate=0.30, ocr_failed=2, citation_invalid=1)]
    assert set(codes(hist)) == {"INSUFFICIENT_SPIKE", "OCR_FAILED", "CITATION_INVALID"}


def test_records_roundtrip_and_dashboard_renders(tmp_path, suite_eval):
    cmp = evals.compare(suite_eval, evals.load_baseline())
    p = tmp_path / "h.jsonl"
    monitor.append(monitor.make_record(suite_eval, cmp, "unit test"), p)
    monitor.append(monitor.make_record(suite_eval, cmp, "again"), p)
    hist = monitor.read(p)
    assert len(hist) == 2 and hist[0]["total"] == suite_eval["total"] and 0 <= hist[0]["insufficient_rate"] <= 1
    out = tmp_path / "m.html"
    monitor.build(hist, out, 0.98)
    html = out.read_text()
    assert "Review monitoring" in html and "<svg" in html and "unit test" in html


def test_alerting_run_is_visible_on_the_dashboard(tmp_path):
    hist = [rec(0.98), rec(0.40, broken=["REQ-3.3"], insufficient_rate=0.4)]
    out = tmp_path / "m.html"
    alerts = monitor.build(hist, out, 0.98)
    html = out.read_text()
    assert any(a[0] == "critical" for a in alerts) and "EVAL_DROP" in html and "REQ-3.3" in html


def test_eval_page_marks_regressions(tmp_path, suite_eval_v2):
    cmp = evals.compare(suite_eval_v2, evals.load_baseline())
    render.build(suite_eval_v2, cmp, tmp_path / "e.html", "chunker v2")
    html = (tmp_path / "e.html").read_text()
    assert "Regression against the baseline" in html and "missed_table_value" in html and "HRD-3.3" in html


def test_monitor_command_exit_code(tmp_path, capsys):
    h = tmp_path / "h.jsonl"
    h.write_text("\n".join(json.dumps(x) for x in [rec(0.98), rec(0.40, broken=["REQ-3.3"])]) + "\n")
    assert cli.main(["monitor", "--history", str(h), "--out", str(tmp_path)]) == 1
    assert "EVAL_DROP" in capsys.readouterr().out and (tmp_path / "monitor.html").exists()
    h.write_text(json.dumps(rec(0.98)) + "\n")
    assert cli.main(["monitor", "--history", str(h), "--out", str(tmp_path)]) == 0
