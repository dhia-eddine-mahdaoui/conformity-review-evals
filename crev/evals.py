"""Evaluation against the gold set, with failure categories and a baseline diff."""
import json
from collections import Counter
from pathlib import Path

import yaml

from .model import INSUFFICIENT, NOT_MET, VERDICTS

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "eval" / "gold.yaml"
BASELINE = ROOT / "eval" / "baseline.json"

CATEGORIES = ("ocr_error", "unit_mismatch", "missed_table_value", "missed_evidence", "wrong_page", "bad_citation")


def load_gold(path=None):
    return {g["id"]: g for g in yaml.safe_load(Path(path or GOLD).read_text(encoding="utf-8"))["gold"]}


def categorize(g, r, verdict_ok, page_ok):
    """Name the most likely reason a requirement failed."""
    diags = set(r["diagnostics"])
    if "CITATION_INVALID" in diags:
        return "bad_citation"
    if not verdict_ok:
        if any(d.startswith("OCR_") for d in diags):
            return "ocr_error"
        if "UNIT_UNRESOLVED" in diags:
            return "unit_mismatch"
        if "ocr" in g["tags"] and r["verdict"] == INSUFFICIENT:
            return "ocr_error"
        if "table" in g["tags"]:
            return "missed_table_value"
        return "missed_evidence"
    if not page_ok:
        return "wrong_page"
    return None


def evaluate(run, gold=None):
    gold = gold or load_gold()
    rows = []
    for r in run["results"]:
        g = gold[r["req_id"]]
        cited = {(e["doc"], e["page"]) for e in r["evidence"]}
        wanted = {(d, p) for d, ps in g["pages"].items() for p in ps}
        verdict_ok = r["verdict"] == g["verdict"]
        page_ok = wanted <= cited
        cat = categorize(g, r, verdict_ok, page_ok)
        rows.append({"id": r["req_id"], "expected": g["verdict"], "got": r["verdict"], "verdict_ok": verdict_ok,
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
    return {
        "meta": run["meta"],
        "rows": rows,
        "passed": sum(x["passed"] for x in rows),
        "total": len(rows),
        "verdict_accuracy": sum(x["verdict_ok"] for x in rows) / len(rows),
        "page_accuracy": sum(x["page_ok"] for x in rows) / len(rows),
        "not_met": {"precision": prec, "recall": rec, "f1": f1, "tp": tp, "fp": fp, "fn": fn},
        "confusion": confusion,
        "categories": dict(Counter(x["category"] for x in rows if x["category"])),
    }


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
    return {"broken": broken, "drops": drops, "ok": not broken and not drops}


def save_baseline(ev, path=None):
    slim = {k: ev[k] for k in ("rows", "verdict_accuracy", "page_accuracy", "not_met", "categories", "passed", "total")}
    Path(path or BASELINE).write_text(json.dumps(slim, indent=2) + "\n", encoding="utf-8")


def load_baseline(path=None):
    p = Path(path or BASELINE)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def format_report(ev, cmp=None):
    m = ev["meta"]
    out = [f"Eval  provider={m['provider']}  chunker={m['chunker']}  ocr={m['ocr_engine']}  chunks={m['chunks']}", ""]
    out.append(f"{'requirement':9} {'expected':13} {'got':13} {'verdict':8} {'pages':6} category / detail")
    for x in ev["rows"]:
        detail = x["category"] or ""
        if x["category"] in ("wrong_page", "missed_table_value", "missed_evidence") and x["cited"]:
            detail += f"  cited {', '.join(x['cited'])}; want {', '.join(x['wanted'])}"
        elif x["category"]:
            detail += "  " + " ".join(x["diagnostics"])
        out.append(f"{x['id']:9} {x['expected']:13} {x['got']:13} {'ok' if x['verdict_ok'] else 'FAIL':8} "
                   f"{'ok' if x['page_ok'] else 'FAIL':6} {'PASS' if x['passed'] else 'FAIL'} {detail}")
    n = ev["not_met"]
    out += ["", f"passed {ev['passed']}/{ev['total']}   verdict accuracy {ev['verdict_accuracy']:.2f}   page accuracy {ev['page_accuracy']:.2f}",
            f"'not met': precision {n['precision']:.2f}  recall {n['recall']:.2f}  f1 {n['f1']:.2f}  (tp {n['tp']}, fp {n['fp']}, fn {n['fn']})",
            "confusion (rows=expected, cols=got): " + "  ".join(f"{e}->" + "/".join(str(ev['confusion'][e][g]) for g in VERDICTS) for e in VERDICTS) + f"   [{'/'.join(VERDICTS)}]"]
    out.append("failure categories: " + (", ".join(f"{k}={v}" for k, v in sorted(ev["categories"].items())) or "none"))
    if cmp is not None:
        if cmp["ok"]:
            out.append("baseline: no regressions")
        else:
            out.append("BASELINE REGRESSION: previously passing now failing: " + (", ".join(cmp["broken"]) or "none"))
            for k, (a, b) in cmp["drops"].items():
                out.append(f"  {k}: {a:.2f} -> {b:.2f}")
    return "\n".join(out)
