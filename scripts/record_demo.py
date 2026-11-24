"""Record docs/demo.gif: a ~25 s screen recording of the real pages, driven by headless Chrome (screenshots resampled to 10 fps).

Scenes: agent review run (replayed real output) -> report with cited verdicts -> trace of one requirement ->
reviewer override with a note -> eval catching the chunker regression (replayed real output) -> monitoring.
Needs `make setup-browser` and `make monitor-demo`; converts with the static ffmpeg from imageio-ffmpeg."""
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from browser_util import ROOT, assert_clean, build_report, launch, suite_eval, terminal_page
from playwright.sync_api import sync_playwright

from crev import evals, monitor, report

W, H = 960, 600
FPS = 10
OUT = ROOT / "docs"


def real_lines():
    work = Path(tempfile.mkdtemp(prefix="crev-demo-"))
    run = build_report("hard", work / "hard", mode="agent")
    verdicts = {}
    for r in run["results"]:
        verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1
    scripted = [("cmd", "crev run --mode agent --case hard", True), ("dim", "", False),
                ("", f"reviewed {len(run['results'])} requirements in {run['meta']['seconds']}s, {run['meta']['steps']} tool calls:", False),
                ("ok", f"  met {verdicts.get('met', 0)}   not met {verdicts.get('not_met', 0)}   insufficient {verdicts.get('insufficient', 0)}", False),
                ("dim", "report written", False)]
    ev, cmp = suite_eval(chunker="v2")
    keep = [x for x in evals.format_report(ev, cmp).splitlines()
            if x.startswith(("passed ", "'not met'", "failure categories"))]
    regress = [("cmd", "crev eval --chunker v2", True), ("dim", "", False)]
    for x in keep:
        regress.append(("bad" if "recall" in x else "", x[:100], False))
    regress.append(("bad", f"BASELINE REGRESSION: {len(cmp['broken'])} requirements that passed now fail", False))
    regress.append(("bad", "exit code 1", False))
    return work, scripted, regress


class Frames:
    """Screenshot-based recorder (playwright's own video needs a separate ffmpeg download): frames are
    stamped with real time and resampled to a fixed rate, so pacing survives a slow machine."""

    def __init__(self, page):
        self.page, self.t0, self.frames = page, time.time(), []

    def snap(self):
        self.frames.append((time.time() - self.t0, self.page.screenshot()))

    def hold(self, ms):
        end = time.time() + ms / 1000
        while time.time() < end:
            self.snap()
            time.sleep(0.04)

    def type(self, text, delay=0.04):
        for ch in text:
            self.page.keyboard.type(ch)
            self.snap()
            time.sleep(delay)

    def wait_done(self, timeout=90):
        end = time.time() + timeout
        while not self.page.evaluate("window.done === true") and time.time() < end:
            self.snap()
            time.sleep(0.05)

    def write(self, folder, fps=FPS):
        n = int(self.frames[-1][0] * fps)
        j = 0
        for k in range(n):
            while j + 1 < len(self.frames) and self.frames[j + 1][0] <= k / fps:
                j += 1
            (Path(folder) / f"f{k:04d}.png").write_bytes(self.frames[j][1])
        return n


def record(work, scripted, regress, folder):
    base = evals.load_baseline()
    hist = monitor.read(monitor.history_path())
    if len(hist) < 3:
        sys.exit("run `make monitor-demo` first")
    monitor.build(hist, work / "monitor.html", base["passed"] / base["total"])
    t1 = terminal_page(work / "t1.html", "Review run", scripted)
    t2 = terminal_page(work / "t2.html", "Eval against the baseline", regress, ms=450)
    for t in scripted + regress:
        assert_clean(t[1])
    srv = report.serve(work / "hard", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with sync_playwright() as pw:
        b = launch(pw)
        p = b.new_page(viewport={"width": W, "height": H})
        rec = Frames(p)
        p.goto(t1.as_uri())
        rec.wait_done()
        rec.hold(1200)
        p.goto(f"http://localhost:{srv.server_address[1]}/")
        rec.hold(1500)
        p.click("#filters button[data-f=not_met]")
        rec.hold(1300)
        sec = p.locator("section[id='HRD-3.1']")
        sec.scroll_into_view_if_needed()
        rec.hold(900)
        sec.locator("summary").click()
        rec.hold(2000)
        p.click("#filters button[data-f=insufficient]")
        rec.hold(900)
        form = p.locator("section[id='HRD-2.7'] form")
        form.scroll_into_view_if_needed()
        rec.hold(500)
        form.locator("select[name=decision]").select_option("override")
        form.locator("select[name=final]").select_option("met")
        rec.hold(600)
        form.locator("input[name=note]").click()
        rec.type("Test conditions on p5 give the supply frequency in words")
        form.locator("input[name=reviewer]").click()
        rec.type("Reviewer", 0.06)
        rec.hold(400)
        form.locator("button").click()
        p.wait_for_selector("section[id='HRD-2.7'] .status.saved:not(:empty)")
        rec.hold(1200)
        p.goto(t2.as_uri())
        rec.wait_done()
        rec.hold(1000)
        p.goto((work / "monitor.html").as_uri())
        rec.hold(2600)
        n = rec.write(folder)
        b.close()
    srv.shutdown()
    srv.server_close()
    return n


def to_gif(folder, gif):
    import imageio_ffmpeg
    pal = "scale=900:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(Path(folder) / "f%04d.png"),
                    "-vf", pal, "-loop", "0", str(gif)], check=True)


def main():
    OUT.mkdir(exist_ok=True)
    work, scripted, regress = real_lines()
    folder = work / "frames"
    folder.mkdir()
    n = record(work, scripted, regress, folder)
    to_gif(folder, OUT / "demo.gif")
    print("wrote docs/demo.gif,", round((OUT / "demo.gif").stat().st_size / 1e6, 2), "MB,", round(n / FPS, 1), "s")


if __name__ == "__main__":
    main()
