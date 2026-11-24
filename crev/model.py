"""Plain data classes shared by the pipeline."""
from dataclasses import asdict, dataclass, field

MET, NOT_MET, INSUFFICIENT = "met", "not_met", "insufficient"
VERDICTS = (MET, NOT_MET, INSUFFICIENT)


@dataclass
class Chunk:
    id: str
    doc: str
    page: int  # 1-based page of the source PDF
    kind: str  # text | table | ocr
    text: str
    bbox: tuple | None = None  # normalised x0,y0,x1,y1 on the page (None for OCR)


@dataclass
class Evidence:
    doc: str
    page: int
    quote: str
    chunk_id: str
    kind: str


@dataclass
class Result:
    req_id: str
    text: str
    verdict: str
    evidence: list = field(default_factory=list)
    rationale: str = ""
    diagnostics: list = field(default_factory=list)
    check: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class DocInfo:
    name: str
    path: str
    n_pages: int
    chunks: list = field(default_factory=list)
    ocr_pages: list = field(default_factory=list)
    ocr_failed: list = field(default_factory=list)


@dataclass
class Corpus:
    docs: dict
    chunker: str
    ocr_engine: str

    def chunks(self, doc=None):
        for name, info in self.docs.items():
            if doc is None or name == doc:
                yield from info.chunks

    def by_id(self, chunk_id):
        for c in self.chunks():
            if c.id == chunk_id:
                return c
        return None
