"""Judgement providers for requirements that need reading, not arithmetic.

HeuristicProvider is the offline default: it applies the accept/reject
patterns written next to the requirement. LLMProvider talks to any
OpenAI-compatible chat endpoint configured through environment variables
(CR_LLM_URL, CR_LLM_MODEL, CR_LLM_KEY); nothing is read from files and no
credentials are stored in the repo. Whatever the provider answers, the quote
must appear verbatim in the chunk it cites, otherwise the answer is
downgraded to "insufficient" (see pipeline.validate_citations).
"""
import json
import os
import re
import urllib.request
from dataclasses import dataclass, field

from .checks import clip
from .model import INSUFFICIENT, MET, NOT_MET, VERDICTS


@dataclass
class Judgement:
    verdict: str
    chunk: object = None
    quote: str = ""
    rationale: str = ""
    diagnostics: list = field(default_factory=list)


def retrieve(corpus, docs, keywords, k=5):
    """Rank chunks by how many distinct keyword patterns they contain."""
    scored = []
    for doc in docs:
        for c in corpus.chunks(doc):
            s = sum(1 for kw in keywords if re.search(kw, c.text, re.I))
            if s:
                scored.append((s, c))
    scored.sort(key=lambda t: -t[0])
    return [c for _, c in scored[:k]]


class HeuristicProvider:
    name = "heuristic"

    def judge(self, req, candidates):
        h = req["heuristic"]
        kw = re.compile("|".join(req["retrieve"]), re.I)
        for c in candidates:
            for line in c.text.splitlines():
                if not kw.search(line):
                    continue
                if re.search(h["reject"], line, re.I):
                    return Judgement(NOT_MET, c, clip(line), "Matching passage shows an unresolved item.")
                if re.search(h["accept"], line, re.I):
                    return Judgement(MET, c, clip(line), "Matching passage shows the item assessed and closed.")
        return Judgement(INSUFFICIENT, None, "", "Relevant passages found but none states an outcome.", ["NO_OUTCOME"])


class LLMProvider:
    name = "llm"

    def __init__(self, post=None):
        self.url = os.environ.get("CR_LLM_URL")
        self.model = os.environ.get("CR_LLM_MODEL", "default")
        self.key = os.environ.get("CR_LLM_KEY", "")
        if not self.url and post is None:
            raise RuntimeError("Set CR_LLM_URL (and CR_LLM_MODEL, CR_LLM_KEY) to use the llm provider.")
        self._post = post or self._http_post

    def _http_post(self, payload):
        req = urllib.request.Request(self.url, json.dumps(payload).encode(), {
            "Content-Type": "application/json", **({"Authorization": f"Bearer {self.key}"} if self.key else {})})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"]

    def judge(self, req, candidates):
        numbered = "\n\n".join(f"[{i}] (page {c.page}) {c.text}" for i, c in enumerate(candidates))
        prompt = (
            "You review a technical file against one requirement. Use only the passages given.\n"
            f"Requirement: {req['text']}\n\nPassages:\n{numbered}\n\n"
            'Answer with JSON: {"verdict": "met|not_met|insufficient", "passage": <index>, '
            '"quote": "<verbatim text copied from that passage>", "rationale": "<one sentence>"}. '
            "If the passages do not decide the requirement answer insufficient."
        )
        raw = self._post({"model": self.model, "temperature": 0,
                          "messages": [{"role": "user", "content": prompt}]})
        try:
            data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
            verdict = data["verdict"]
            chunk = candidates[int(data["passage"])] if verdict != INSUFFICIENT else None
            if verdict not in VERDICTS:
                raise ValueError(verdict)
            return Judgement(verdict, chunk, str(data.get("quote", "")), str(data.get("rationale", "")))
        except (AttributeError, KeyError, ValueError, IndexError, TypeError):
            return Judgement(INSUFFICIENT, None, "", "Provider answer could not be parsed.", ["PROVIDER_PARSE"])


def get_provider(name):
    if name == "heuristic":
        return HeuristicProvider()
    if name == "llm":
        return LLMProvider()
    raise ValueError(f"unknown provider {name!r}")
