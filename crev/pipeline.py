"""Run every requirement against the corpus and verify the citations."""
import hashlib
import re
from pathlib import Path

import yaml

from . import chunkers
from .checks import CHECKS
from .ingest import load_corpus
from .model import INSUFFICIENT
from .providers import get_provider

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def load_requirements(path=None):
    return yaml.safe_load(Path(path or DATA / "requirements.yaml").read_text(encoding="utf-8"))["requirements"]


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


def run(data_dir=None, reqs_path=None, provider="heuristic", chunker=None, ocr_mode="auto"):
    data_dir = Path(data_dir or DATA / "techfile")
    chunker = chunker or chunkers.DEFAULT
    corpus = load_corpus(data_dir, chunker, ocr_mode)
    prov = get_provider(provider) if isinstance(provider, str) else provider
    results = []
    for req in load_requirements(reqs_path):
        res = CHECKS[req["kind"]](req, corpus, prov)
        results.append(validate_citations(res, corpus))
    digest = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(data_dir.glob("*.pdf")))).hexdigest()[:12]
    return {
        "run_id": digest + "-" + chunker + "-" + prov.name,
        "meta": {"provider": prov.name, "chunker": chunker, "ocr_engine": corpus.ocr_engine,
                 "inputs_sha": digest, "docs": {n: d.n_pages for n, d in corpus.docs.items()},
                 "chunks": sum(len(d.chunks) for d in corpus.docs.values()),
                 "ocr_pages": {n: d.ocr_pages for n, d in corpus.docs.items() if d.ocr_pages},
                 "ocr_failed": {n: d.ocr_failed for n, d in corpus.docs.items() if d.ocr_failed}},
        "results": [r.to_dict() for r in results],
    }
