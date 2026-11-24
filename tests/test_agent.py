"""Agent mode: tool loop, trace, guards, and the LLM policy against a local fake endpoint."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from crev import agent, pipeline
from crev.agent import Action, Agent, LLMPolicy, ScriptedPolicy, Toolbox
from crev.providers import LLMProvider


def verdicts(run):
    return {r["req_id"]: (r["verdict"], sorted((e["doc"], e["page"]) for e in r["evidence"])) for r in run["results"]}


def test_scripted_agent_matches_the_fixed_pipeline(suite_runs, agent_runs):
    for (_, base), (_, ag) in zip(suite_runs, agent_runs):
        assert verdicts(ag) == verdicts(base)
        assert ag["meta"]["mode"] == "agent" and ag["meta"]["steps"] > len(ag["results"])


def test_every_agent_citation_is_verbatim(agent_runs):
    for case, run in agent_runs:
        corpus = pipeline.load_corpus(case["data"])
        for r in run["results"]:
            assert "CITATION_INVALID" not in r["diagnostics"]
            for e in r["evidence"]:
                assert " ".join(e["quote"].split()).lower() in " ".join(corpus.by_id(e["chunk_id"]).text.split()).lower()


def test_trace_shows_the_tools_used(agent_runs):
    hard = {r["req_id"]: r for r in agent_runs[1][1]["results"]}
    tools = [t["tool"] for t in hard["HRD-3.1"]["trace"]]
    assert tools[0] == "search_chunks" and "read_table" in tools and "compare_values" in tools and tools[-1] == "finish"
    cmp_steps = [t for t in hard["HRD-3.1"]["trace"] if t["tool"] == "compare_values"]
    assert len(cmp_steps) == 3 and '"result": false' in cmp_steps[2]["observation"]  # 45000 kOhm < 50 MOhm
    assert "read_page" in [t["tool"] for t in hard["HRD-2.4"]["trace"]]  # OCR value checked against the whole page
    assert any(d.startswith("ORIENTATION_CORRECTED") for d in hard["HRD-2.4"]["diagnostics"])


@pytest.fixture(scope="module")
def corpus():
    return pipeline.load_corpus(pipeline.DATA / "techfile")


def test_tools_report_errors_instead_of_raising(corpus):
    t = Toolbox(corpus)
    assert "error" in t.call("nope", {})
    assert "error" in t.call("read_page", {"doc": "missing", "page": 1})
    assert "error" in t.call("search_chunks", {"regex": "("})
    assert "error" in t.call("read_table", {"doc": "test_report", "page": 1})
    assert t.call("compare_values", {"a": "0.25 GOhm", "b": "100 MOhm", "op": ">="})["result"] is True
    assert t.call("compare_values", {"a": "0.62 mA", "b": "0.5 V", "op": "<="})["error"] == "UNIT_MISMATCH"
    assert t.call("search_chunks", {"regex": "^touch current", "doc": "test_report"})["hits"][0]["page"] == 9


class Script:
    """A policy that replays fixed actions (stands in for a model)."""
    name = "script"

    def __init__(self, *actions):
        self.actions = list(actions)

    def begin(self, req, tools):
        pass

    def decide(self, req, trace, obs):
        return self.actions.pop(0)


REQ = {"id": "R", "text": "touch current", "kind": "limit"}


def fin(verdict, quote, page=9, doc="test_report"):
    return Action("finish", {"verdict": verdict, "evidence": [{"doc": doc, "page": page, "quote": quote}], "rationale": "x"})


def test_agent_downgrades_fabricated_quotes(corpus):
    res = Agent(corpus, Script(fin("met", "All touch currents are negligible."))).review(REQ)
    pipeline.validate_citations(res, corpus)
    assert res.verdict == "insufficient" and "CITATION_INVALID" in res.diagnostics


def test_agent_accepts_a_real_quote_and_requires_evidence(corpus):
    ok = Agent(corpus, Script(fin("not_met", "Touch current, single fault condition | 0.62 | mA"))).review(REQ)
    assert pipeline.validate_citations(ok, corpus).verdict == "not_met"
    bare = Agent(corpus, Script(Action("finish", {"verdict": "met", "evidence": [], "rationale": "trust me"}))).review(REQ)
    assert bare.verdict == "insufficient" and "NO_EVIDENCE" in bare.diagnostics
    bad = Agent(corpus, Script(Action("finish", {"verdict": "yes", "evidence": []}))).review(REQ)
    assert "AGENT_BAD_VERDICT" in bad.diagnostics


def test_step_budget_is_enforced(corpus):
    loop = Script(*[Action("list_documents", {})] * 20)
    res = Agent(corpus, loop, max_steps=4).review(REQ)
    assert res.verdict == "insufficient" and "MAX_STEPS" in res.diagnostics and len(res.trace) == 4


def test_scripted_policy_reports_missing_ocr():
    no_ocr = pipeline.load_corpus(pipeline.DATA / "techfile", ocr_mode="none")
    req = next(r for r in pipeline.load_requirements() if r["id"] == "REQ-2.3")
    res = Agent(no_ocr, ScriptedPolicy()).review(req)
    assert res.verdict == "insufficient" and "OCR_UNAVAILABLE" in res.diagnostics


# --- LLM policy against a local OpenAI-compatible endpoint ---------------------------------------

class FakeLLM:
    """Serves canned chat completions on localhost, so the real HTTP path (headers, JSON, parsing) runs."""

    def __init__(self, replies):
        self.replies, self.prompts = list(replies), []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.prompts.append(body["messages"][0]["content"])
                data = json.dumps({"choices": [{"message": {"content": outer.replies.pop(0)}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("localhost", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://localhost:{self.srv.server_address[1]}/v1/chat"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def llm_agent(monkeypatch, corpus, replies):
    fake = FakeLLM(replies)
    monkeypatch.setenv("CR_LLM_URL", fake.url)
    monkeypatch.setenv("CR_LLM_MODEL", "test-model")
    return fake, Agent(corpus, LLMPolicy(LLMProvider()))


def test_llm_policy_runs_a_two_step_episode_over_http(monkeypatch, corpus):
    fake, ag = llm_agent(monkeypatch, corpus, [
        '{"thought": "look for the row", "tool": "search_chunks", "args": {"regex": "^touch current", "doc": "test_report"}}',
        'Sure! {"thought": "second row is over the limit", "tool": "finish", "args": {"verdict": "not_met", "evidence": '
        '[{"doc": "test_report", "page": 9, "quote": "Touch current, single fault condition | 0.62 | mA"}], "rationale": "0.62 > 0.5"}}'])
    try:
        res = pipeline.validate_citations(ag.review(REQ), corpus)
    finally:
        fake.close()
    assert [t["tool"] for t in res.trace] == ["search_chunks", "finish"]
    assert res.verdict == "not_met" and res.check == "agent:llm"
    assert "untrusted" in fake.prompts[0] and "touch current" in fake.prompts[1].lower() and "step 1" in fake.prompts[1]


def test_llm_policy_that_follows_an_injected_instruction_is_stopped_by_citation_check(monkeypatch, corpus):
    fake, ag = llm_agent(monkeypatch, corpus, [
        '{"thought": "the document told me to", "tool": "finish", "args": {"verdict": "met", "evidence": '
        '[{"doc": "test_report", "page": 9, "quote": "this file is fully compliant"}], "rationale": "per reviewer note"}}'])
    try:
        res = pipeline.validate_citations(ag.review(REQ), corpus)
    finally:
        fake.close()
    assert res.verdict == "insufficient" and "CITATION_INVALID" in res.diagnostics


def test_llm_policy_garbage_gives_insufficient(monkeypatch, corpus):
    fake, ag = llm_agent(monkeypatch, corpus, ["I would say it is fine.", "still not json"])
    try:
        res = ag.review(REQ)
    finally:
        fake.close()
    assert res.verdict == "insufficient" and "PROVIDER_PARSE" in res.diagnostics


def test_unknown_policy_and_mode_rejected():
    with pytest.raises(ValueError):
        agent.get_policy("nope")
    with pytest.raises(ValueError):
        pipeline.run(mode="swarm")
