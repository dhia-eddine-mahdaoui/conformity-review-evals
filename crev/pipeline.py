"""Run every requirement against the corpus and verify the citations."""
import hashlib
import re
import time
from pathlib import Path

import yaml

from . import chunkers
from .agent import Agent, get_policy
from .checks import CHECKS
from .ingest import load_corpus
from .model import INSUFFICIENT
from .providers import get_provider

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SUITE = ROOT / "eval" / "suite.yaml"


def load_requirements(path=None):
    return yaml.safe_load(Path(path or DATA / "requirements.yaml").read_text(encoding="utf-8"))["requirements"]


def load_suite(path=None):
    """Cases of the eval suite with paths resolved against the repo root."""
    cases = yaml.safe_load(Path(path or SUITE).read_text(encoding="utf-8"))["cases"]
    return [{**c, **{k: str(ROOT / c[k]) for k in ("data", "requirements", "gold")}} for c in cases]


def _norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def validate_citations(result, corpus):
    """A quote is only valid if it appears verbatim in the cited chunk."""
    for e in result.evidence:
        chunk = corpus.by_id(e.chunk_id)
        if chunk is None or _norm(e.quote) not in _norm(chunk.text):
            result.diagnostics.append("CITATION_INVALID")
            result.verdict = INSUFFICIENT
            result.rationale += " Citation could not be verified against the source text."
            return result
    return result


def run(data_dir=None, reqs_path=None, provider="heuristic", chunker=None, ocr_mode="auto",
        mode="pipeline", policy="scripted", title=None):
    """mode "pipeline": one deterministic check per requirement. mode "agent": a tool-using loop per requirement."""
    t0 = time.time()
    data_dir = Path(data_dir or DATA / "techfile")
    chunker = chunker or chunkers.DEFAULT
    corpus = load_corpus(data_dir, chunker, ocr_mode)
    results, pol = [], None
    if mode == "agent":
        pol = get_policy(policy) if isinstance(policy, str) else policy
        agent = Agent(corpus, pol)
        prov = None
    elif mode == "pipeline":
        prov = get_provider(provider) if isinstance(provider, str) else provider
    else:
        raise ValueError(f"unknown mode {mode!r}; choose pipeline or agent")
    for req in load_requirements(reqs_path):
        res = agent.review(req) if mode == "agent" else CHECKS[req["kind"]](req, corpus, prov)
        results.append(validate_citations(res, corpus))
    digest = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(data_dir.glob("*.pdf")))).hexdigest()[:12]
    who = ("agent-" + pol.name) if mode == "agent" else prov.name
    return {
        "run_id": digest + "-" + chunker + "-" + who,
        "meta": {"title": title or data_dir.name, "mode": mode, "provider": who, "chunker": chunker, "ocr_engine": corpus.ocr_engine,
                 "inputs_sha": digest, "docs": {n: d.n_pages for n, d in corpus.docs.items()},
                 "chunks": sum(len(d.chunks) for d in corpus.docs.values()),
                 "ocr_pages": {n: d.ocr_pages for n, d in corpus.docs.items() if d.ocr_pages},
                 "ocr_failed": {n: d.ocr_failed for n, d in corpus.docs.items() if d.ocr_failed},
                 "ocr_rotated": {n: d.ocr_rotated for n, d in corpus.docs.items() if d.ocr_rotated},
                 "steps": sum(len(r.trace) for r in results),
                 "llm_calls": getattr(pol, "calls", 0),
                 "seconds": round(time.time() - t0, 2)},
        "results": [r.to_dict() for r in results],
    }
