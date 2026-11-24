"""Chunking policies.

v1 keeps one chunk per paragraph / table / OCR page and the page number of
the page the text came from.

v2 is the "fewer, bigger chunks" refactor used for the regression demo (see
README): it merges neighbouring chunks into windows of up to WINDOW characters
and flattens tables to a single line so that they read like prose. It looks
reasonable in a diff and halves the chunk count, but it loses page identity
(a window is labelled with the page of its first chunk) and table row
structure. DEFAULT is what the pipeline uses when nothing is requested.
"""
from .model import Chunk

DEFAULT = "v2"
WINDOW = 1200


def _number(doc, chunks):
    out = []
    for i, c in enumerate(chunks):
        out.append(Chunk(f"{doc}:p{c.page}:c{i}", c.doc, c.page, c.kind, c.text, c.bbox))
    return out


def v1(doc, per_page):
    return _number(doc, [c for page in per_page for c in page])


def v2(doc, per_page):
    merged, cur = [], None
    for page in per_page:
        for c in page:
            if c.kind == "ocr":  # scanned pages are kept whole
                merged.append(Chunk("", c.doc, c.page, "ocr", c.text, None))
                cur = None
                continue
            text = c.text
            if c.kind == "table":
                text = " ".join(" ".join(row.split(" | ")) for row in text.splitlines())
            if cur is not None and len(cur.text) + len(text) < WINDOW:
                cur.text += "\n" + text
            else:
                cur = Chunk("", c.doc, c.page, "text", text, None)
                merged.append(cur)
    return _number(doc, merged)


POLICIES = {"v1": v1, "v2": v2}


def apply(name, doc, per_page):
    if name not in POLICIES:
        raise ValueError(f"unknown chunker {name!r}; choose from {sorted(POLICIES)}")
    return POLICIES[name](doc, per_page)
