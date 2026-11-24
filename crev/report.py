"""Single-page HTML review report and the tiny local server behind it."""
import json
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import audit

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Conformity review</title>
<style>
:root{--bg:#fafaf8;--fg:#1d2420;--mut:#5f6b64;--line:#d9ddd7;--card:#fff;--met:#1d6b3a;--not:#a3261b;--ins:#8a5a00}
@media (prefers-color-scheme:dark){:root{--bg:#161a17;--fg:#e7ebe6;--mut:#9aa69e;--line:#2c342e;--card:#1e231f;--met:#6fcf8c;--not:#ff8a7d;--ins:#e8b44f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}h1{font-size:22px;margin:0 0 4px}
.meta{color:var(--mut);font-size:13px}.sum{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}
.pill{border:1px solid var(--line);border-radius:99px;padding:2px 12px;font-size:13px;background:var(--card)}
.req{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin:12px 0}
.req h2{font-size:15px;margin:0 0 6px}.req h2 .top{display:flex;gap:10px;align-items:baseline}.req h2 .txt{display:block;margin-top:2px}
.badge{font-size:12px;font-weight:600;padding:1px 9px;border-radius:4px;border:1px solid currentColor}
.met{color:var(--met)}.not_met{color:var(--not)}.insufficient{color:var(--ins)}
blockquote{margin:8px 0;padding:6px 10px;border-left:3px solid var(--line);font:13px/1.45 ui-monospace,monospace;overflow-wrap:anywhere}
.why{color:var(--mut);font-size:13px}.diag{font-size:12px;color:var(--ins)}
form{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;align-items:center}
input,select,button{font:inherit;font-size:13px;padding:4px 8px;border:1px solid var(--line);border-radius:5px;background:var(--bg);color:var(--fg)}
input.note{flex:1;min-width:200px}button{cursor:pointer}.saved{font-size:13px;color:var(--met)}.err{font-size:13px;color:var(--not)}
a{color:inherit}
.filters{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0 2px;position:sticky;top:0;background:var(--bg);padding:6px 0;z-index:2}.filters button{border-radius:99px;padding:3px 12px}
.filters button[aria-pressed=true]{background:var(--fg);color:var(--bg);border-color:var(--fg)}
details.trace{margin-top:8px;border-top:1px dashed var(--line);padding-top:6px}details.trace summary{cursor:pointer;font-size:13px;color:var(--mut)}
.steps{width:100%;border-collapse:collapse;margin-top:6px;font-size:12.5px}.steps td{padding:4px 6px;border-bottom:1px solid var(--line);vertical-align:top}
.steps td:first-child{color:var(--mut);width:28px}.steps .tool{font:12px ui-monospace,monospace;white-space:nowrap}.steps .obs{font:12px ui-monospace,monospace;color:var(--mut);overflow-wrap:anywhere}
.steps tr.err .obs{color:var(--not)}.steps tr.fin td{font-weight:600}
@media (max-width:640px){.steps .tool{white-space:normal;overflow-wrap:anywhere}.steps td:nth-child(2){display:none}}
</style></head><body><main>
<h1 id="title">Conformity review</h1>
<div class="meta" id="meta"></div><div class="sum" id="sum"></div><div class="filters" id="filters" role="group" aria-label="Filter by verdict"></div>
<div id="list"></div>
<p class="meta">Decisions are written to <code>audit.jsonl</code> by the local server (<code>make serve</code>). Opened as a plain file the form cannot save.</p>
</main>
<script>
const RUN = __DATA__;
const L = {met:"Met",not_met:"Not met",insufficient:"Insufficient evidence"};
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const pdf = d => "techfile/" + d + ".pdf";
const m = RUN.meta;
document.getElementById("title").textContent = "Conformity review: " + (m.title || "technical file");
document.title = "Conformity review: " + (m.title || "technical file");
document.getElementById("meta").textContent = `run ${RUN.run_id} | ${m.mode === "agent" ? "agent mode" : "pipeline mode"} | chunker ${m.chunker} | OCR ${m.ocr_engine} | ${m.chunks} chunks` + (m.steps ? ` | ${m.steps} tool calls` : "");
const counts = {};
RUN.results.forEach(r => counts[r.verdict] = (counts[r.verdict]||0)+1);
document.getElementById("sum").innerHTML = Object.keys(L).map(k => `<span class="pill ${k}">${L[k]}: ${counts[k]||0}</span>`).join("");
document.getElementById("filters").innerHTML = [["all","All"], ...Object.entries(L)].map(([k,t],i) => `<button type="button" data-f="${k}" aria-pressed="${i===0}">${t}</button>`).join("");
document.querySelectorAll("#filters button").forEach(b => b.onclick = () => {
  document.querySelectorAll("#filters button").forEach(x => x.setAttribute("aria-pressed", x === b));
  document.querySelectorAll("section.req").forEach(s => s.hidden = b.dataset.f !== "all" && s.dataset.v !== b.dataset.f);
});
const trace = r => !(r.trace && r.trace.length) ? "" : `<details class="trace"><summary>Agent trace: ${r.trace.length} steps</summary><table class="steps">` +
  r.trace.map(t => `<tr class="${t.error ? "err" : ""}${t.tool === "finish" ? " fin" : ""}"><td>${t.step}</td><td>${esc(t.thought)}</td><td><span class="tool">${esc(t.tool)}(${esc(Object.entries(t.args).map(([k,v]) => k + "=" + (typeof v === "string" ? v : JSON.stringify(v))).join(", "))})</span><div class="obs">${esc(t.observation)}</div></td></tr>`).join("") + "</table></details>";
document.getElementById("list").innerHTML = RUN.results.map(r => {
  const ev = r.evidence.map(e => `<blockquote>${esc(e.quote)}<br><a href="${pdf(e.doc)}#page=${e.page}" target="_blank">${esc(e.doc)}, page ${e.page}</a> <span class="meta">(${e.kind})</span></blockquote>`).join("") || `<div class="why">No supporting passage found.</div>`;
  const diag = r.diagnostics.length ? `<div class="diag">diagnostics: ${esc(r.diagnostics.join(", "))}</div>` : "";
  return `<section class="req" id="${r.req_id}" data-v="${r.verdict}"><h2><span class="top"><span>${r.req_id}</span><span class="badge ${r.verdict}">${L[r.verdict]}</span></span><span class="txt">${esc(r.text)}</span></h2>
  ${ev}<div class="why">${esc(r.rationale)} <span class="meta">[${esc(r.check)}]</span></div>${diag}${trace(r)}
  <form data-id="${r.req_id}"><select name="decision"><option value="accept">Accept system verdict</option><option value="override">Override</option></select>
  <select name="final" hidden>${Object.keys(L).map(k=>`<option value="${k}">${L[k]}</option>`).join("")}</select>
  <input class="note" name="note" placeholder="Note (required for override)"><input name="reviewer" placeholder="Reviewer" size="12">
  <button>Save</button><span class="status saved" aria-live="polite"></span></form></section>`;
}).join("");
document.querySelectorAll("form").forEach(f => {
  f.decision.onchange = () => f.final.hidden = f.decision.value !== "override";
  f.onsubmit = async ev => {
    ev.preventDefault();
    const out = f.querySelector(".status"); out.className = "status saved"; out.textContent = "";
    try {
      const r = await fetch("/api/review", {method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({req_id:f.dataset.id, decision:f.decision.value, final_verdict:f.final.value, note:f.note.value, reviewer:f.reviewer.value})});
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || r.status);
      out.textContent = "Saved " + j.ts;
    } catch (e) { out.className = "status err"; out.textContent = "Not saved: " + e.message; }
  };
});
</script></body></html>
"""


def build(run, out_dir, data_dir):
    out = Path(out_dir)
    (out / "techfile").mkdir(parents=True, exist_ok=True)
    for pdf in Path(data_dir).glob("*.pdf"):
        shutil.copy(pdf, out / "techfile" / pdf.name)
    (out / "results.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    safe = json.dumps(run).replace("</", "<\\/")
    (out / "report.html").write_text(PAGE.replace("__DATA__", safe), encoding="utf-8")
    return out / "report.html"


def make_handler(out_dir):
    out = Path(out_dir).resolve()
    audit_path = out / "audit.jsonl"

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?")[0].split("#")[0]
            if path == "/api/audit":
                return self._send(200, audit.read(audit_path))
            rel = "report.html" if path in ("/", "") else path.lstrip("/")
            f = (out / rel).resolve()
            if out not in f.parents or not f.is_file() or f.name == "audit.jsonl":
                return self._send(404, {"error": "not found"})
            ctype = {".html": "text/html; charset=utf-8", ".pdf": "application/pdf", ".json": "application/json"}.get(f.suffix, "application/octet-stream")
            self._send(200, f.read_bytes(), ctype)

        def do_POST(self):
            if self.path != "/api/review":
                return self._send(404, {"error": "not found"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                run = json.loads((out / "results.json").read_text(encoding="utf-8"))
                entry = audit.append(audit_path, run, body.get("req_id"), body.get("decision"), body.get("reviewer", ""),
                                     body.get("final_verdict"), body.get("note", ""))
            except (ValueError, KeyError, TypeError) as e:
                return self._send(400, {"error": str(e)})
            self._send(200, entry)

        def log_message(self, *a):
            pass

    return Handler


def serve(out_dir, port=8765):
    srv = ThreadingHTTPServer(("localhost", port), make_handler(out_dir))
    return srv
