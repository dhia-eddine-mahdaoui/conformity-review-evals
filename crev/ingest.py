"""PDF -> page-numbered chunks (text paragraphs, tables, OCR pages).

Evidence boxes are stored as page-normalised coordinates so a viewer can
highlight the source regardless of page size.
"""
import functools
from pathlib import Path

import pymupdf

from . import chunkers, ocr
from .model import Chunk, Corpus, DocInfo

MAX_PARA = 700
MARGIN_TOP, MARGIN_BOTTOM = 55, 60


def _norm(rect, page):
    r = page.rect
    return (round(rect[0] / r.width, 4), round(rect[1] / r.height, 4),
            round(rect[2] / r.width, 4), round(rect[3] / r.height, 4))


def _split_long(text):
    if len(text) <= MAX_PARA:
        return [text]
    out, cur = [], ""
    for sentence in text.replace("\n", " ").split(". "):
        if len(cur) + len(sentence) > MAX_PARA and cur:
            out.append(cur.strip())
            cur = ""
        cur += sentence + ". "
    return out + [cur.strip()]


def _page_chunks(doc_name, page, ocr_texts):
    """Raw per-page chunks before the chunker policy is applied."""
    n = page.number + 1
    raw = []
    tables = []
    # find_tables is slow; only try pages that draw rectangles (ruled tables)
    has_rects = any(it[0] == "re" for d in page.get_drawings() for it in d["items"])
    try:
        tables = list(page.find_tables().tables) if has_rects else []
    except Exception:  # find_tables can fail on odd pages; fall back to text only
        pass
    boxes = [pymupdf.Rect(t.bbox) for t in tables]
    for t in tables:
        rows = [[" ".join(page.get_text("text", clip=pymupdf.Rect(c)).split()) if c else "" for c in row.cells]
                for row in t.rows]
        text = "\n".join(" | ".join(r) for r in rows if any(r))
        if text:
            raw.append(Chunk("", doc_name, n, "table", text, _norm(t.bbox, page)))
    plain = ""
    for x0, y0, x1, y1, text, _, btype in page.get_text("blocks"):
        if btype != 0 or y1 < MARGIN_TOP or y0 > page.rect.height - MARGIN_BOTTOM:
            continue
        if any(pymupdf.Rect(x0, y0, x1, y1).intersects(b) for b in boxes):
            continue
        plain += text
        text = text.strip()
        if text:
            for part in _split_long(text):
                raw.append(Chunk("", doc_name, n, "text", part, _norm((x0, y0, x1, y1), page)))
    raw.sort(key=lambda c: (c.bbox[1], c.bbox[0]))
    return raw, plain


@functools.lru_cache(maxsize=8)
def _extract_all(directory, ocr_mode):
    """Chunker-independent extraction, memoised because table detection is slow."""
    out, engine = {}, ocr.engine_name(ocr_mode)
    for pdf in sorted(Path(directory).glob("*.pdf")):
        name = pdf.stem
        with pymupdf.open(pdf) as d:
            info = DocInfo(name, pdf.name, len(d))
            per_page, sparse = [], []
            for page in d:
                raw, plain = _page_chunks(name, page, None)
                if len(plain.strip()) < ocr.SPARSE_CHARS and page.get_images():
                    sparse.append((page.number + 1, page.get_pixmap(dpi=200, colorspace=pymupdf.csGRAY).tobytes("png")))
                per_page.append(raw)
            if sparse:
                texts, engine = ocr.recognize([png for _, png in sparse], ocr_mode)
                for (n, _), text in zip(sparse, texts):
                    if text is None:
                        info.ocr_failed.append(n)
                        continue
                    info.ocr_pages.append(n)
                    lines = "\n".join(l.strip() for l in text.splitlines() if l.strip())
                    if lines:
                        per_page[n - 1].append(Chunk("", name, n, "ocr", lines, None))
        out[name] = (info, per_page)
    return out, engine


def load_corpus(directory, chunker="v1", ocr_mode="auto"):
    raw, engine = _extract_all(str(Path(directory).resolve()), ocr_mode)
    docs = {}
    for name, (info, per_page) in raw.items():
        docs[name] = DocInfo(info.name, info.path, info.n_pages, chunkers.apply(chunker, name, per_page),
                             list(info.ocr_pages), list(info.ocr_failed))
    return Corpus(docs, chunker, engine)
