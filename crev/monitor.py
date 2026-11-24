"""Run history and monitoring: one JSON line per eval run, alert rules, and a static HTML dashboard.

A record keeps what a reviewer-facing product would watch after launch: the verdict mix, the
insufficient-evidence rate, how often pages needed OCR (and how often OCR failed), the eval score
against the gold set, citation failures, step counts and run time. Alerts compare a run with the
baseline and with the recent history of the same kind of run.

    python -m crev eval --label "chunker v2"      # appends to out/history.jsonl
    python -m crev monitor                        # writes out/monitor.html, exit 1 if the latest run alerts
"""
import html
import json
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path

from .model import INSUFFICIENT, MET, NOT_MET

ROOT = Path(__file__).resolve().parents[1]
SCORE_DROP = 0.05       # alert when the eval score falls this far below the baseline score
INSUFFICIENT_JUMP = 0.10  # ... or the insufficient-evidence rate rises this far above the recent median


def history_path(out_dir=None):
    return Path(os.environ.get("CR_HISTORY") or Path(out_dir or ROOT / "out") / "history.jsonl")


def make_record(ev, cmp=None, label=""):
    s, m = ev["stats"], ev["meta"]
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "label": label, "run_id": f"{m['inputs_sha']}-{m['chunker']}-{m['provider']}",
        "mode": m.get("mode", "pipeline"), "provider": m["provider"], "chunker": m["chunker"], "ocr": m["ocr_engine"],
        "passed": ev["passed"], "total": ev["total"], "score": ev["passed"] / ev["total"],
        "verdict_accuracy": ev["verdict_accuracy"], "page_accuracy": ev["page_accuracy"],
        "not_met_precision": ev["not_met"]["precision"], "not_met_recall": ev["not_met"]["recall"],
        "verdicts": s["verdicts"], "insufficient_rate": s["insufficient_rate"],
        "ocr_fallback_rate": s["ocr_fallback_rate"], "ocr_failed": s["ocr_failed"], "rotated_pages": s["rotated_pages"],
        "citation_invalid": s["citation_invalid"], "steps": s["steps"], "seconds": s["seconds"],
        "categories": ev["categories"], "broken": (cmp or {}).get("broken", []),
        "baseline_score": (cmp or {}).get("baseline_score"),
    }


def append(record, path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def read(path):
    p = Path(path)
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def alerts_for(rec, previous, baseline_score=None):
    """Alerts for one record given the records before it. Each alert: (severity, code, message)."""
    out = []
    base = baseline_score if baseline_score is not None else rec.get("baseline_score")
    if base is not None and rec["score"] < base - SCORE_DROP:
        out.append(("critical", "EVAL_DROP", f"eval score {rec['score']:.2f} is below the baseline {base:.2f}"))
    if rec["broken"]:
        out.append(("critical", "REGRESSION", "previously passing: " + ", ".join(rec["broken"][:8]) + (" ..." if len(rec["broken"]) > 8 else "")))
    recent = [r["insufficient_rate"] for r in previous[-8:] if r["mode"] == rec["mode"]]
    if recent and rec["insufficient_rate"] > statistics.median(recent) + INSUFFICIENT_JUMP:
        out.append(("warning", "INSUFFICIENT_SPIKE", f"insufficient-evidence rate {rec['insufficient_rate']:.0%} vs recent median {statistics.median(recent):.0%}"))
    if rec["ocr_failed"]:
        out.append(("warning", "OCR_FAILED", f"{rec['ocr_failed']} scanned page(s) could not be read"))
    if rec["citation_invalid"]:
        out.append(("warning", "CITATION_INVALID", f"{rec['citation_invalid']} verdict(s) downgraded: quote not found in source"))
    return out


def all_alerts(history, baseline_score=None):
    return [alerts_for(r, history[:i], baseline_score) for i, r in enumerate(history)]


# --- dashboard ------------------------------------------------------------------------------------------

CSS = """
:root{--bg:#fafaf8;--fg:#1d2420;--mut:#5f6b64;--line:#d9ddd7;--card:#fff;--met:#1d6b3a;--not:#a3261b;--ins:#8a5a00;--acc:#2b5d8a;--crit-bg:#fdecea;--warn-bg:#fff5df}
@media (prefers-color-scheme:dark){:root{--bg:#161a17;--fg:#e7ebe6;--mut:#9aa69e;--line:#2c342e;--card:#1e231f;--met:#6fcf8c;--not:#ff8a7d;--ins:#e8b44f;--acc:#7fb2e0;--crit-bg:#3a1f1c;--warn-bg:#392d14}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:1040px;margin:0 auto;padding:24px 16px 56px}h1{font-size:22px;margin:0 0 4px}h2{font-size:14px;margin:0 0 8px;color:var(--mut);font-weight:600}
.meta{color:var(--mut);font-size:13px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:16px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px}.card b{display:block;font-size:24px;line-height:1.2}
.card span{font-size:12px;color:var(--mut)}.bad b{color:var(--not)}
.alert{border-radius:8px;padding:8px 12px;margin:6px 0;font-size:14px;border:1px solid var(--line)}
.alert.critical{background:var(--crit-bg);border-color:var(--not)}.alert.warning{background:var(--warn-bg);border-color:var(--ins)}
.alert code{font-weight:700}.ok{color:var(--met)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;margin:14px 0}
.panel{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
svg{width:100%;height:auto;display:block}svg text{fill:var(--mut);font:11px system-ui,sans-serif}.panel .meta{margin-top:4px}
table{border-collapse:collapse;width:100%;font-size:13px;background:var(--card);border:1px solid var(--line);border-radius:8px}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--mut);font-weight:600}
td.n{text-align:right;font-variant-numeric:tabular-nums}.tbl{overflow-x:auto;margin-top:14px}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px}
"""


def _line_chart(title, recs, key, base=None, fmt="{:.0%}", flag=None, lo=0.0, hi=1.0, note=""):
    W, H, L, R, T, B = 330, 150, 36, 12, 14, 24
    n = len(recs)
    xs = [L + (W - L - R) * (i / max(n - 1, 1) if n > 1 else 0.5) for i in range(n)]
    y = lambda v: T + (H - T - B) * (1 - (v - lo) / ((hi - lo) or 1))
    g = []
    for t in (lo, (lo + hi) / 2, hi):
        g.append(f'<line x1="{L}" x2="{W - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" stroke="var(--line)"/>'
                 f'<text x="{L - 5}" y="{y(t) + 4:.1f}" text-anchor="end">{fmt.format(t)}</text>')
    if base is not None:
        g.append(f'<line x1="{L}" x2="{W - R}" y1="{y(base):.1f}" y2="{y(base):.1f}" stroke="var(--ins)" stroke-dasharray="5 4"/>'
                 f'<text x="{L + 4}" y="{y(base) + 12:.1f}">baseline {fmt.format(base)}</text>')
    pts = " ".join(f"{x:.1f},{y(r[key]):.1f}" for x, r in zip(xs, recs))
    g.append(f'<polyline points="{pts}" fill="none" stroke="var(--acc)" stroke-width="2"/>')
    for i, (x, r) in enumerate(zip(xs, recs)):
        bad = flag and flag[i]
        g.append(f'<circle cx="{x:.1f}" cy="{y(r[key]):.1f}" r="{5 if bad else 3.5}" fill="{"var(--not)" if bad else "var(--acc)"}"/>')
        g.append(f'<text x="{x:.1f}" y="{H - 8}" text-anchor="middle">{i + 1}</text>')
    last = recs[-1]
    g.append(f'<text x="{xs[-1]:.1f}" y="{y(last[key]) - 9:.1f}" text-anchor="{"end" if n > 1 else "middle"}" style="fill:var(--fg);font-weight:600;font-size:12px">{fmt.format(last[key])}</text>')
    return f'<div class="panel"><h2>{html.escape(title)}</h2><svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(title)}">{"".join(g)}</svg><div class="meta">{html.escape(note)}</div></div>'


def _mix_chart(recs):
    W, H, L, R, T, B = 330, 150, 36, 12, 14, 24
    n = len(recs)
    bw = min(34, (W - L - R) / max(n, 1) * 0.7)
    out = []
    for t in (0, 0.5, 1):
        yy = T + (H - T - B) * (1 - t)
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="var(--line)"/><text x="{L - 5}" y="{yy + 4:.1f}" text-anchor="end">{t:.0%}</text>')
    for i, r in enumerate(recs):
        cx = L + (W - L - R) * ((i + 0.5) / n)
        total = sum(r["verdicts"].values()) or 1
        top = H - B
        for k, col in ((MET, "var(--met)"), (NOT_MET, "var(--not)"), (INSUFFICIENT, "var(--ins)")):
            h = (H - T - B) * r["verdicts"][k] / total
            top -= h
            out.append(f'<rect x="{cx - bw / 2:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{h:.1f}" fill="{col}"><title>{k}: {r["verdicts"][k]}</title></rect>')
        out.append(f'<text x="{cx:.1f}" y="{H - 8}" text-anchor="middle">{i + 1}</text>')
    legend = "".join(f'<span style="margin-right:12px"><i class="dot" style="background:{c}"></i>{l}</span>' for l, c in
                     (("met", "var(--met)"), ("not met", "var(--not)"), ("insufficient", "var(--ins)")))
    return f'<div class="panel"><h2>Verdict mix per run</h2><svg viewBox="0 0 {W} {H}" role="img" aria-label="Verdict mix per run">{"".join(out)}</svg><div class="meta">{legend}</div></div>'


def build(history, out_path, baseline_score=None):
    recs = history[-12:]
    offset = len(history) - len(recs)
    al = all_alerts(history, baseline_score)[offset:]
    last, last_al = recs[-1], al[-1]
    if baseline_score is None:
        baseline_score = last.get("baseline_score")
    cards = [
        ("Eval score", f"{last['passed']}/{last['total']}", f"baseline {baseline_score:.0%}" if baseline_score is not None else "", any(a[1] in ("EVAL_DROP", "REGRESSION") for a in last_al)),
        ("Insufficient evidence", f"{last['insufficient_rate']:.0%}", f"{last['verdicts'][INSUFFICIENT]} of {sum(last['verdicts'].values())} verdicts", any(a[1] == "INSUFFICIENT_SPIKE" for a in last_al)),
        ("Pages needing OCR", f"{last['ocr_fallback_rate']:.1%}", f"{last['ocr_failed']} failed, {last['rotated_pages']} turned upright", last["ocr_failed"] > 0),
        ("Citation failures", str(last["citation_invalid"]), "quote not found in source", last["citation_invalid"] > 0),
        ("Run time", f"{last['seconds']:.0f} s", f"{last['steps']} agent steps" if last["steps"] else "pipeline mode", False),
    ]
    cards_html = "".join(f'<div class="card{" bad" if bad else ""}"><span>{html.escape(t)}</span><b>{html.escape(v)}</b><span>{html.escape(s)}</span></div>' for t, v, s, bad in cards)
    alert_html = "".join(f'<div class="alert {s}"><code>{html.escape(c)}</code> {html.escape(m)}</div>' for s, c, m in last_al) \
        or '<div class="alert"><span class="ok"><b>No alerts</b></span> on the latest run.</div>'
    past = "".join(
        f'<div class="alert {s}"><b>run {i + 1 + offset}</b> ({html.escape(recs[i]["label"] or recs[i]["run_id"])}) <code>{html.escape(c)}</code> {html.escape(m)}</div>'
        for i, x in enumerate(al[:-1]) for s, c, m in x)
    past_html = f'<h2 style="margin-top:14px">Earlier alerts in this window</h2>{past}' if past else ""
    flag = [any(a[0] == "critical" for a in x) for x in al]
    floor = lambda v: max(0.0, int((v - 0.05) * 10) / 10)
    lo = floor(min([r["score"] for r in recs] + ([baseline_score] if baseline_score is not None else [])))
    charts = (_line_chart("Eval score vs baseline", recs, "score", baseline_score, flag=flag, lo=lo, note="gold-set items passed; red = critical alert")
              + _line_chart("Insufficient-evidence rate", recs, "insufficient_rate", note="share of verdicts with no usable evidence")
              + _line_chart("OCR fallback rate", recs, "ocr_fallback_rate", fmt="{:.0%}", hi=0.1, note="scanned pages / all pages")
              + _mix_chart(recs))
    rows = "".join(
        f"<tr><td class='n'>{i + 1 + offset}</td><td>{html.escape(r['ts'][5:19].replace('T', ' '))}</td><td>{html.escape(r['label'] or '-')}</td>"
        f"<td>{html.escape(r['mode'])} / {html.escape(r['chunker'])} / ocr {html.escape(r['ocr'])}</td>"
        f"<td class='n'>{r['passed']}/{r['total']}</td><td class='n'>{r['insufficient_rate']:.0%}</td>"
        f"<td>{html.escape(', '.join(f'{k} {v}' for k, v in sorted(r['categories'].items())) or '-')}</td>"
        f"<td>{html.escape(', '.join(a[1] for a in a_) or 'ok')}</td></tr>" for i, (r, a_) in enumerate(zip(recs, al)))
    page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>Review monitoring</title><style>{CSS}</style></head><body><main>"
            f'<h1>Review monitoring</h1><div class="meta">{len(history)} runs recorded, showing the last {len(recs)}. Latest: {html.escape(last["label"] or last["run_id"])}</div>'
            f'<div class="cards">{cards_html}</div>{alert_html}{past_html}<div class="grid">{charts}</div>'
            f'<div class="tbl"><table><thead><tr><th>#</th><th>time (UTC)</th><th>label</th><th>configuration</th><th>score</th><th>insuff.</th><th>failure categories</th><th>alerts</th></tr></thead><tbody>{rows}</tbody></table></div>'
            "</main></body></html>")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(page, encoding="utf-8")
    return last_al
