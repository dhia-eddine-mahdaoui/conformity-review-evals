"""Eval results as a standalone HTML page (same data as the CLI table, easier to read and to share)."""
import html
from pathlib import Path

from .model import VERDICTS
from .monitor import CSS

EXTRA = """
.tag{font-size:11px;border:1px solid var(--line);border-radius:4px;padding:0 5px;margin-right:3px;color:var(--mut)}
.pass{color:var(--met);font-weight:600}.fail{color:var(--not);font-weight:600}.met{color:var(--met)}.not_met{color:var(--not)}.insufficient{color:var(--ins)}
.bar{display:flex;align-items:center;gap:8px;font-size:13px;margin:3px 0}.bar i{display:block;height:9px;border-radius:2px;background:var(--met)}
.bar .name{width:150px;color:var(--mut)}.bar .track{flex:1;background:var(--line);border-radius:2px;height:9px;max-width:260px}
.banner{border-radius:8px;padding:10px 14px;margin:12px 0;border:1px solid var(--line);background:var(--card)}
.banner.bad{background:var(--crit-bg);border-color:var(--not)}.banner.good{border-color:var(--met)}
td.mono{font-family:ui-monospace,monospace;font-size:12px}
"""


def _pct(x):
    return f"{x:.2f}"


def build(ev, cmp, out_path, label=""):
    m, n = ev["meta"], ev["not_met"]
    cards = [("Passed", f"{ev['passed']}/{ev['total']}"), ("Verdict accuracy", _pct(ev["verdict_accuracy"])),
             ("Page accuracy", _pct(ev["page_accuracy"])), ("'Not met' recall", _pct(n["recall"])), ("'Not met' precision", _pct(n["precision"]))]
    bad_cards = {"Passed": ev["passed"] < ev["total"] and cmp is not None and not cmp["ok"],
                 "'Not met' recall": n["recall"] < 1, "Page accuracy": ev["page_accuracy"] < 0.95}
    cards_html = "".join(f'<div class="card{" bad" if bad_cards.get(t) else ""}"><span>{t}</span><b>{v}</b></div>' for t, v in cards)
    if cmp is None:
        banner = ""
    elif cmp["ok"]:
        extra = f" Newly passing since the baseline: {html.escape(', '.join(cmp['fixed']))}." if cmp["fixed"] else ""
        banner = f'<div class="banner good"><b class="ok">No regression against the baseline.</b>{extra}</div>'
    else:
        drops = "; ".join(f"{k} {a:.2f} to {b:.2f}" for k, (a, b) in cmp["drops"].items())
        banner = (f'<div class="banner bad"><b class="fail">Regression against the baseline.</b> {len(cmp["broken"])} previously passing '
                  f'requirement(s) now fail: {html.escape(", ".join(cmp["broken"]))}.<br><span class="meta">{html.escape(drops)}</span></div>')
    cats = "".join(f'<span class="tag" style="color:var(--not)">{html.escape(k)} {v}</span>' for k, v in sorted(ev["categories"].items())) or '<span class="ok">none</span>'
    cases = " &middot; ".join(f"{html.escape(v['title'])}: <b>{v['passed']}/{v['total']}</b>" for v in ev.get("cases", {}).values())
    tags = "".join(
        f'<div class="bar"><span class="name">{html.escape(t)}</span><span class="track"><i style="width:{100 * b["passed"] / b["total"]:.0f}%;'
        f'{"" if b["passed"] == b["total"] else "background:var(--not)"}"></i></span><span>{b["passed"]}/{b["total"]}</span></div>'
        for t, b in sorted(ev["by_tag"].items(), key=lambda kv: (kv[1]["passed"] / kv[1]["total"], -kv[1]["total"], kv[0])))
    def row(x):
        detail = ""
        if not x["passed"]:
            detail = f"cited {', '.join(x['cited']) or 'nothing'}; want {', '.join(x['wanted']) or 'nothing'}"
            if x["diagnostics"]:
                detail += "; " + ", ".join(x["diagnostics"])
        return (f"<tr><td>{x['id']}</td><td>{''.join(f'<span class=tag>{html.escape(t)}</span>' for t in x['tags'][:3])}</td>"
                f"<td class='{x['expected']}'>{x['expected']}</td><td class='{x['got']}'>{x['got']}</td>"
                f"<td class='{'pass' if x['passed'] else 'fail'}'>{'PASS' if x['passed'] else 'FAIL'}</td>"
                f"<td>{html.escape(x['category'] or '')}</td><td class='mono'>{html.escape(detail)}</td></tr>")
    failing = [x for x in ev["rows"] if not x["passed"]]
    fail_tbl = ("<div class='tbl'><table><thead><tr><th>requirement</th><th>tags</th><th>expected</th><th>got</th><th></th><th>category</th><th>detail</th></tr></thead><tbody>"
                + "".join(row(x) for x in failing) + "</tbody></table></div>") if failing else "<p class='ok'><b>Every requirement passes.</b></p>"
    all_tbl = ("<div class='tbl'><table><thead><tr><th>requirement</th><th>tags</th><th>expected</th><th>got</th><th></th><th>category</th><th>detail</th></tr></thead><tbody>"
               + "".join(row(x) for x in ev["rows"]) + "</tbody></table></div>")
    conf = ev["confusion"]
    conf_html = "<table style='width:auto'><thead><tr><th>expected / got</th>" + "".join(f"<th>{g}</th>" for g in VERDICTS) + "</tr></thead><tbody>" + "".join(
        f"<tr><th>{e}</th>" + "".join(f"<td class='n'>{conf[e][g]}</td>" for g in VERDICTS) + "</tr>" for e in VERDICTS) + "</tbody></table>"
    page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>Eval results</title><style>{CSS}{EXTRA}</style></head><body><main>"
            f"<h1>Eval results{(': ' + html.escape(label)) if label else ''}</h1>"
            f'<div class="meta">mode {html.escape(m.get("mode", "pipeline"))} &middot; provider {html.escape(m["provider"])} &middot; chunker {html.escape(m["chunker"])} '
            f'&middot; OCR {html.escape(m["ocr_engine"])} &middot; {ev["stats"]["pages"]} pages, {m["chunks"]} chunks</div>'
            f'<div class="meta">{cases}</div>'
            f'<div class="cards">{cards_html}</div>{banner}'
            f'<h2>Failure categories</h2><div>{cats}</div>'
            f'<div class="grid"><div class="panel"><h2>Pass rate by item tag (weakest first)</h2>{tags}</div>'
            f'<div class="panel"><h2>Confusion matrix</h2>{conf_html}</div></div>'
            f"<h2>Failing requirements</h2>{fail_tbl}<details><summary class='meta'>All {ev['total']} requirements</summary>{all_tbl}</details>"
            "</main></body></html>")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(page, encoding="utf-8")
    return Path(out_path)
