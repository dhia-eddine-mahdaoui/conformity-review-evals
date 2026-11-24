"""Evaluation against the gold set, with failure categories and a baseline diff."""
import json
from collections import Counter
from pathlib import Path

import yaml

from .model import INSUFFICIENT, NOT_MET, VERDICTS

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "eval" / "gold.yaml"
BASELINE = ROOT / "eval" / "baseline.json"

CATEGORIES = ("ocr_error", "rotation_error", "unit_mismatch", "number_format", "missed_table_value", "split_table",
              "distractor", "conflict_missed", "injection_followed", "missed_evidence", "wrong_page", "bad_citation")


def load_gold(path=None):
    return {g["id"]: g for g in yaml.safe_load(Path(path or GOLD).read_text(encoding="utf-8"))["gold"]}


def categorize(g, r, verdict_ok, page_ok):
    """Name the most likely reason a requirement failed."""
    diags = set(r["diagnostics"])
    if "CITATION_INVALID" in diags:
        return "bad_citation"
    if not verdict_ok:
        tags = set(g["tags"])
        if "injection" in tags and r["verdict"] != INSUFFICIENT and g["verdict"] == INSUFFICIENT:
            return "injection_followed"
        if any(d.startswith("OCR_") for d in diags) or ("ocr" in tags and r["verdict"] == INSUFFICIENT):
            return "rotation_error" if "rotated_scan" in tags else "ocr_error"
        if "UNIT_UNRESOLVED" in diags:
            return "unit_mismatch"
        if "table" in tags and diags & {"NO_ROW", "NO_OUTCOME"}:  # the row itself could not be found
            return "missed_table_value"
        if "number_format" in tags:
            return "number_format"
        if "distractor" in tags and "table" in tags and r["verdict"] != g["verdict"]:
            return "distractor"
        if "split_table" in tags:
            return "split_table"
        if "conflict" in tags:
            return "conflict_missed"
        if "table" in g["tags"]:
            return "missed_table_value"
        return "missed_evidence"
    if not page_ok:
        return "wrong_page"
    return None


def evaluate(run, gold=None, case="core"):
    gold = gold or load_gold()
    rows = []
    for r in run["results"]:
        g = gold[r["req_id"]]
        cited = {(e["doc"], e["page"]) for e in r["evidence"]}
        wanted = {(d, p) for d, ps in g["pages"].items() for p in ps}
        verdict_ok = r["verdict"] == g["verdict"]
        page_ok = wanted <= cited
        cat = categorize(g, r, verdict_ok, page_ok)
        rows.append({"id": r["req_id"], "case": case, "tags": g["tags"], "steps": len(r.get("trace") or []), "expected": g["verdict"], "got": r["verdict"], "verdict_ok": verdict_ok,
                     "page_ok": page_ok, "passed": cat is None, "category": cat,
                     "cited": sorted(f"{d} p{p}" for d, p in cited), "wanted": sorted(f"{d} p{p}" for d, p in wanted),
                     "rationale": r["rationale"], "diagnostics": r["diagnostics"]})
    tp = sum(1 for x in rows if x["expected"] == NOT_MET and x["got"] == NOT_MET)
    fp = sum(1 for x in rows if x["expected"] != NOT_MET and x["got"] == NOT_MET)
    fn = sum(1 for x in rows if x["expected"] == NOT_MET and x["got"] != NOT_MET)
    prec = tp / (tp + fp) if tp + fp else 1.0
    rec = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    confusion = {e: {g_: 0 for g_ in VERDICTS} for e in VERDICTS}
    for x in rows:
        confusion[x["expected"]][x["got"]] += 1
    got = Counter(x["got"] for x in rows)
    by_tag = {}
    for x in rows:
        for t in x["tags"]:
            b = by_tag.setdefault(t, {"passed": 0, "total": 0})
            b["total"] += 1
            b["passed"] += x["passed"]
    pages = sum(run["meta"]["docs"].values())
    ocr_n = sum(len(v) for v in run["meta"]["ocr_pages"].values())
    failed_n = sum(len(v) for v in run["meta"]["ocr_failed"].values())
    stats = {"results": len(rows), "verdicts": {v: got.get(v, 0) for v in VERDICTS},
             "insufficient_rate": got.get(INSUFFICIENT, 0) / len(rows),
             "pages": pages, "ocr_pages": ocr_n, "ocr_failed": failed_n,
             "ocr_fallback_rate": (ocr_n + failed_n) / pages if pages else 0.0,
             "rotated_pages": sum(len(v) for v in run["meta"].get("ocr_rotated", {}).values()),
             "citation_invalid": sum("CITATION_INVALID" in r["diagnostics"] for r in run["results"]),
             "steps": run["meta"].get("steps", 0), "seconds": run["meta"].get("seconds", 0.0)}
    return {
        "meta": run["meta"],
        "stats": stats,
        "by_tag": by_tag,
        "rows": rows,
        "passed": sum(x["passed"] for x in rows),
        "total": len(rows),
        "verdict_accuracy": sum(x["verdict_ok"] for x in rows) / len(rows),
        "page_accuracy": sum(x["page_ok"] for x in rows) / len(rows),
        "not_met": {"precision": prec, "recall": rec, "f1": f1, "tp": tp, "fp": fp, "fn": fn},
        "confusion": confusion,
        "categories": dict(Counter(x["category"] for x in rows if x["category"])),
    }


def combine(evs):
    """Merge per-case evaluations (list of (case_name, ev)) into one suite-level evaluation."""
    rows = [x for _, e in evs for x in e["rows"]]
    tp = sum(e["not_met"]["tp"] for _, e in evs)
    fp = sum(e["not_met"]["fp"] for _, e in evs)
    fn = sum(e["not_met"]["fn"] for _, e in evs)
    prec = tp / (tp + fp) if tp + fp else 1.0
    rec = tp / (tp + fn) if tp + fn else 1.0
    confusion = {e_: {g_: sum(e["confusion"][e_][g_] for _, e in evs) for g_ in VERDICTS} for e_ in VERDICTS}
    by_tag = {}
    for _, e in evs:
        for t, b in e["by_tag"].items():
            a = by_tag.setdefault(t, {"passed": 0, "total": 0})
            a["passed"] += b["passed"]
            a["total"] += b["total"]
    s = [e["stats"] for _, e in evs]
    verdicts = {v: sum(x["verdicts"][v] for x in s) for v in VERDICTS}
    n, pages = sum(x["results"] for x in s), sum(x["pages"] for x in s)
    stats = {"results": n, "verdicts": verdicts, "insufficient_rate": verdicts[INSUFFICIENT] / n, "pages": pages,
             "ocr_pages": sum(x["ocr_pages"] for x in s), "ocr_failed": sum(x["ocr_failed"] for x in s),
             "rotated_pages": sum(x["rotated_pages"] for x in s), "citation_invalid": sum(x["citation_invalid"] for x in s),
             "steps": sum(x["steps"] for x in s), "seconds": round(sum(x["seconds"] for x in s), 2)}
    stats["ocr_fallback_rate"] = (stats["ocr_pages"] + stats["ocr_failed"]) / pages if pages else 0.0
    return {
        "meta": {**evs[0][1]["meta"], "title": " + ".join(e["meta"].get("title", c) for c, e in evs),
                 "chunks": sum(e["meta"]["chunks"] for _, e in evs)},
        "cases": {c: {"passed": e["passed"], "total": e["total"], "title": e["meta"].get("title", c)} for c, e in evs},
        "stats": stats, "by_tag": by_tag, "rows": rows,
        "passed": sum(e["passed"] for _, e in evs), "total": len(rows),
        "verdict_accuracy": sum(x["verdict_ok"] for x in rows) / len(rows),
        "page_accuracy": sum(x["page_ok"] for x in rows) / len(rows),
        "not_met": {"precision": prec, "recall": rec, "f1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0,
                    "tp": tp, "fp": fp, "fn": fn},
        "confusion": confusion,
        "categories": dict(Counter(x["category"] for x in rows if x["category"])),
    }


def evaluate_suite(runs):
    """runs: list of (case dict, pipeline run). Returns the combined evaluation."""
    return combine([(c["name"], evaluate(r, load_gold(c["gold"]), c["name"])) for c, r in runs])


def compare(current, baseline):
    """Requirements that passed in the baseline and fail now, plus metric drops."""
    was = {x["id"]: x for x in baseline["rows"]}
    broken = [x["id"] for x in current["rows"] if was.get(x["id"], {}).get("passed") and not x["passed"]]
    drops = {}
    for k in ("verdict_accuracy", "page_accuracy"):
        if current[k] < baseline[k]:
            drops[k] = (baseline[k], current[k])
    for k in ("precision", "recall"):
        if current["not_met"][k] < baseline["not_met"][k]:
            drops[f"not_met_{k}"] = (baseline["not_met"][k], current["not_met"][k])
    fixed = [x["id"] for x in current["rows"] if x["passed"] and was.get(x["id"], {}).get("passed") is False]
    return {"broken": broken, "fixed": fixed, "drops": drops, "ok": not broken and not drops,
            "score": current["passed"] / current["total"], "baseline_score": baseline["passed"] / baseline["total"]}


def save_baseline(ev, path=None):
    slim = {k: ev[k] for k in ("rows", "verdict_accuracy", "page_accuracy", "not_met", "categories", "passed", "total")}
    slim["rows"] = [{k: x[k] for k in ("id", "case", "expected", "got", "passed", "category")} for x in ev["rows"]]
    Path(path or BASELINE).write_text(json.dumps(slim, indent=2) + "\n", encoding="utf-8")


def load_baseline(path=None):
    p = Path(path or BASELINE)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def format_report(ev, cmp=None):
    m = ev["meta"]
    out = [f"Eval  mode={m.get('mode', 'pipeline')}  provider={m['provider']}  chunker={m['chunker']}  ocr={m['ocr_engine']}  chunks={m['chunks']}", ""]
    out.append(f"{'requirement':9} {'expected':13} {'got':13} {'verdict':8} {'pages':6} category / detail")
    for x in ev["rows"]:
        detail = x["category"] or ""
        if x["category"] in ("wrong_page", "missed_table_value", "missed_evidence", "split_table", "distractor") and x["cited"]:
            detail += f"  cited {', '.join(x['cited'])}; want {', '.join(x['wanted'])}"
        elif x["category"]:
            detail += "  " + " ".join(x["diagnostics"])
        out.append(f"{x['id']:9} {x['expected']:13} {x['got']:13} {'ok' if x['verdict_ok'] else 'FAIL':8} "
                   f"{'ok' if x['page_ok'] else 'FAIL':6} {'PASS' if x['passed'] else 'FAIL'} {detail}")
    n = ev["not_met"]
    out += ["", f"passed {ev['passed']}/{ev['total']}   verdict accuracy {ev['verdict_accuracy']:.2f}   page accuracy {ev['page_accuracy']:.2f}",
            f"'not met': precision {n['precision']:.2f}  recall {n['recall']:.2f}  f1 {n['f1']:.2f}  (tp {n['tp']}, fp {n['fp']}, fn {n['fn']})",
            "confusion (rows=expected, cols=got): " + "  ".join(f"{e}->" + "/".join(str(ev['confusion'][e][g]) for g in VERDICTS) for e in VERDICTS) + f"   [{'/'.join(VERDICTS)}]"]
    if "cases" in ev:
        out.append("by case: " + ", ".join(f"{k} {v['passed']}/{v['total']}" for k, v in ev["cases"].items()))
    out.append("failure categories: " + (", ".join(f"{k}={v}" for k, v in sorted(ev["categories"].items())) or "none"))
    if cmp is not None:
        if cmp["ok"]:
            out.append("baseline: no regressions" + (f" (newly passing: {', '.join(cmp['fixed'])})" if cmp["fixed"] else ""))
        else:
            out.append("BASELINE REGRESSION: previously passing now failing: " + (", ".join(cmp["broken"]) or "none"))
            for k, (a, b) in cmp["drops"].items():
                out.append(f"  {k}: {a:.2f} -> {b:.2f}")
    return "\n".join(out)
