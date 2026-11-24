"""Opens the generated report in a real headless browser. Skipped unless playwright and a Chrome/Chromium
exist (make setup-browser)."""
import shutil
import threading

import pytest

from crev import report

sync_api = pytest.importorskip("playwright.sync_api")


def chrome():
    return shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")


@pytest.fixture(scope="module")
def browser():
    exe = chrome()
    if not exe:
        pytest.skip("no Chrome/Chromium found")
    pw = sync_api.sync_playwright().start()
    b = pw.chromium.launch(executable_path=exe, args=["--no-sandbox"])
    yield b
    b.close()
    pw.stop()


@pytest.fixture(scope="module")
def agent_report(tmp_path_factory, agent_runs):
    case, run = agent_runs[1]
    out = tmp_path_factory.mktemp("rep")
    report.build(run, out, case["data"])
    return out / "report.html", run


def open_report(browser, path, width):
    errors = []
    page = browser.new_page(viewport={"width": width, "height": 900})
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(path.as_uri())
    return page, errors


@pytest.mark.parametrize("width", [1280, 375])
def test_report_renders_without_errors_or_horizontal_scroll(browser, agent_report, width):
    path, run = agent_report
    page, errors = open_report(browser, path, width)
    assert errors == []
    assert page.locator("section.req").count() == len(run["results"])
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    assert "BX-90" in page.locator("h1").inner_text()
    page.close()


def test_filter_buttons_and_trace_work(browser, agent_report):
    path, run = agent_report
    page, errors = open_report(browser, path, 1000)
    n_not_met = sum(r["verdict"] == "not_met" for r in run["results"])
    page.click("#filters button[data-f=not_met]")
    assert page.locator("section.req:visible").count() == n_not_met
    page.click("#filters button[data-f=all]")
    page.locator("section[id='HRD-3.1'] summary").click()
    assert page.locator("section[id='HRD-3.1'] table.steps tr").count() >= 5
    assert "compare_values" in page.locator("section[id='HRD-3.1'] table.steps").inner_text()
    assert errors == []
    page.close()


def test_override_requires_a_note_when_served(browser, tmp_path, suite_runs):
    case, run = suite_runs[0]
    report.build(run, tmp_path, case["data"])
    srv = report.serve(tmp_path, 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        page = browser.new_page()
        page.goto(f"http://localhost:{srv.server_address[1]}/")
        form = page.locator("section[id='REQ-3.3'] form")
        form.locator("select[name=decision]").select_option("override")
        form.locator("button").click()
        page.wait_for_selector("section[id='REQ-3.3'] .err")
        assert "note" in form.locator(".err").inner_text().lower()
        form.locator("input[name=note]").fill("lab re-test attached")
        form.locator("input[name=reviewer]").fill("tester")
        form.locator("button").click()
        page.wait_for_selector("section[id='REQ-3.3'] .status.saved:not(:empty)")
        page.close()
    finally:
        srv.shutdown()
        srv.server_close()
