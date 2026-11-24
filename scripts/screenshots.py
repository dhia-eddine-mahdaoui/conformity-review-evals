"""Regenerate docs/screenshots/*.png from real runs, in headless Chrome. Needs `make setup-browser` and
`make monitor-demo` (the dashboard is drawn from out/history.jsonl)."""
import sys

from browser_util import ROOT, build_report, launch, suite_eval
from playwright.sync_api import sync_playwright

from crev import evals, monitor, render

DOCS = ROOT / "docs" / "screenshots"
WORK = ROOT / "out" / "shots"


def main():
    DOCS.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    hist = monitor.read(monitor.history_path())
    if len(hist) < 3:
        sys.exit("run `make monitor-demo` first: the dashboard needs a few recorded runs")
    build_report("core", WORK / "core")
    build_report("hard", WORK / "hard_agent", mode="agent")
    ev, cmp = suite_eval()
    render.build(ev, cmp, WORK / "eval.html")
    ev2, cmp2 = suite_eval(chunker="v2")
    render.build(ev2, cmp2, WORK / "eval_regressed.html", "chunker v2 merge")
    base = evals.load_baseline()
    monitor.build(hist, WORK / "monitor.html", base["passed"] / base["total"])

    with sync_playwright() as pw:
        b = launch(pw)
        page = b.new_page(viewport={"width": 1100, "height": 760})
        page.goto((WORK / "core" / "report.html").as_uri())
        page.click("#filters button[data-f=not_met]")
        page.screenshot(path=str(DOCS / "report.png"), clip={"x": 40, "y": 0, "width": 1020, "height": 760})
        page.goto((WORK / "hard_agent" / "report.html").as_uri())
        page.click("#filters button[data-f=met]")
        sec = page.locator("section[id='HRD-2.4']")
        sec.locator("summary").click()
        sec.screenshot(path=str(DOCS / "agent-trace.png"))
        page.set_viewport_size({"width": 1100, "height": 900})
        page.goto((WORK / "monitor.html").as_uri())
        page.screenshot(path=str(DOCS / "monitoring.png"), full_page=True)
        page.goto((WORK / "eval.html").as_uri())
        page.screenshot(path=str(DOCS / "eval-baseline.png"), clip={"x": 0, "y": 0, "width": 1100, "height": 900})
        page.goto((WORK / "eval_regressed.html").as_uri())
        page.screenshot(path=str(DOCS / "eval-regression.png"), clip={"x": 0, "y": 0, "width": 1100, "height": 900})
        b.close()
    print("wrote", ", ".join(sorted(p.name for p in DOCS.glob("*.png"))))


if __name__ == "__main__":
    main()
