"""Shared helpers for the screenshot and demo-recording scripts (headless Chrome through playwright)."""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crev import evals, pipeline, report  # noqa: E402


def launch(pw):
    exe = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
    return pw.chromium.launch(executable_path=exe, args=["--no-sandbox"]) if exe else pw.chromium.launch()


def case(name):
    return next(c for c in pipeline.load_suite() if c["name"] == name)


def build_report(name, out, **kw):
    c = case(name)
    run = pipeline.run(c["data"], c["requirements"], title=c["title"], **kw)
    report.build(run, out, c["data"])
    return run


def suite_eval(**kw):
    runs = [(c, pipeline.run(c["data"], c["requirements"], title=c["title"], **kw)) for c in pipeline.load_suite()]
    ev = evals.evaluate_suite(runs)
    return ev, evals.compare(ev, evals.load_baseline())


TERMINAL = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;height:100%;background:#12161a;color:#d6dde3;font:15px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.win{margin:28px auto;width:calc(100% - 56px);height:calc(100% - 56px);background:#1a2026;border-radius:10px;border:1px solid #2c353d;overflow:hidden;display:flex;flex-direction:column}
.bar{padding:9px 14px;background:#232b32;color:#8b98a3;font:13px system-ui,sans-serif;border-bottom:1px solid #2c353d}
.body{padding:16px 20px;white-space:pre-wrap;overflow:hidden}.cmd{color:#7fd0a0}.dim{color:#8b98a3}.bad{color:#ff8a7d}.ok{color:#6fcf8c}
</style></head><body><div class="win"><div class="bar">__TITLE__</div><div class="body" id="b"></div></div><script>
const L = __LINES__, ms = __MS__; const b = document.getElementById("b"); let i = 0;
function esc(s){return s.replace(/&/g,"&amp;").replace(/</g,"&lt;")}
function next(){ if(i>=L.length){window.done=true;return}
  const [cls, txt, typed] = L[i++]; const d=document.createElement("div"); d.className=cls; b.appendChild(d);
  if(!typed){d.innerHTML=esc(txt)||"&nbsp;";setTimeout(next,ms);return}
  let k=0; const t=setInterval(()=>{d.textContent=txt.slice(0,++k); if(k>=txt.length){clearInterval(t);setTimeout(next,350)}},38)}
setTimeout(next,300);
</script></body></html>"""


def terminal_page(path, title, lines, ms=170):
    """lines: (css class, text, typed). Replays real output line by line; no prompt, path or host is shown."""
    html = TERMINAL.replace("__TITLE__", title).replace("__LINES__", json.dumps(lines)).replace("__MS__", str(ms))
    Path(path).write_text(html, encoding="utf-8")
    return Path(path)


def assert_clean(text):
    """Refuse to put anything path-, host- or address-like into a recording."""
    import re
    if re.search(r"(\d{1,3}\.){3}\d{1,3}|/ho" "me/|@|[A-Za-z]:\\\\", text):
        raise AssertionError(f"{text!r} would leak into a recording")
