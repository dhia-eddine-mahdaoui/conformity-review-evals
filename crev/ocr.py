"""OCR fallback for pages without a usable text layer.

Adapted from the page-reading approach of an earlier PDF review tool: a page
whose extracted text is shorter than SPARSE_CHARS is rendered to an image and
sent to a local English OCR engine. Engines, first available wins:

  1. the `tesseract` command line program
  2. tesseract.js through node (see ocr/, installed by `make setup`)
  3. none: the page is flagged and the pipeline reports OCR_UNAVAILABLE

Results are cached on disk by image hash so repeated runs are fast.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OCR_DIR = ROOT / "ocr"
CACHE = Path(os.environ.get("CR_CACHE", ROOT / ".cache" / "ocr"))
SPARSE_CHARS = 24


def engine_name(mode="auto"):
    if mode == "none":
        return "none"
    if mode in ("auto", "tesseract") and shutil.which("tesseract"):
        return "tesseract-cli"
    if mode in ("auto", "node") and shutil.which("node") and (OCR_DIR / "node_modules" / "tesseract.js").is_dir():
        return "tesseract-js"
    return "none"


def _run(engine, pngs):
    if engine == "tesseract-cli":
        out = []
        for png in pngs:
            with tempfile.TemporaryDirectory() as d:
                f = Path(d) / "p.png"
                f.write_bytes(png)
                r = subprocess.run(["tesseract", str(f), "-", "-l", "eng", "--psm", "6"],
                                   capture_output=True, text=True, timeout=120)
                out.append(r.stdout if r.returncode == 0 else None)
        return out
    with tempfile.TemporaryDirectory() as d:
        files = []
        for i, png in enumerate(pngs):
            f = Path(d) / f"{i}.png"
            f.write_bytes(png)
            files.append(str(f))
        r = subprocess.run(["node", str(OCR_DIR / "ocr.mjs"), str(OCR_DIR), *files],
                           capture_output=True, text=True, timeout=300, cwd=OCR_DIR)
        if r.returncode != 0:
            return [None] * len(pngs)
        return json.loads(r.stdout)


def recognize(pngs, mode="auto"):
    """Return (texts, engine). texts[i] is None when OCR was not possible."""
    engine = engine_name(mode)
    if engine == "none":
        return [None] * len(pngs), engine
    CACHE.mkdir(parents=True, exist_ok=True)
    keys = [hashlib.sha1(engine.encode() + p).hexdigest() for p in pngs]
    texts = [None] * len(pngs)
    todo = []
    for i, k in enumerate(keys):
        f = CACHE / f"{k}.txt"
        if f.exists():
            texts[i] = f.read_text(encoding="utf-8")
        else:
            todo.append(i)
    if todo:
        fresh = _run(engine, [pngs[i] for i in todo])
        for i, t in zip(todo, fresh):
            texts[i] = t
            if t is not None:
                (CACHE / f"{keys[i]}.txt").write_text(t, encoding="utf-8")
    return texts, engine


# --- orientation handling ----------------------------------------------------------------------

GOOD_QUALITY = 0.5
_WORD = re.compile(r"^[A-Za-z]{3,}[:.,;]?$")
_NUM = re.compile(r"^[-+<>=]*\d+(?:[.,]\d+)?[%A-Za-z/()]{0,6}[:.,;]?$")


def quality(text):
    """Share of tokens that look like words or numbers (0..1). Sideways or upside-down pages come out as
    short fragments and symbols, so they score low; a clean page scores well above GOOD_QUALITY."""
    toks = text.split()
    if len(toks) < 3:
        return 0.0
    ok = sum(1 for t in toks if (_WORD.match(t) and re.search(r"[aeiouAEIOU]", t)) or _NUM.match(t))
    return ok / len(toks)


def _turn(png, quarter_turns):
    import numpy as np
    import pymupdf
    pix = pymupdf.Pixmap(png)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    arr = np.ascontiguousarray(np.rot90(arr, quarter_turns))
    return pymupdf.Pixmap(pix.colorspace, arr.shape[1], arr.shape[0], arr.tobytes(), False).tobytes("png")


def recognize_oriented(pngs, mode="auto"):
    """OCR with orientation recovery: pages whose text quality is low are retried turned by 90, 270 and
    180 degrees and the best reading wins. Returns (texts, engine, angles) where angles[i] is the
    clockwise turn (0/90/180/270) that was applied to page i."""
    texts, engine = recognize(pngs, mode)
    angles = [0] * len(pngs)
    if engine == "none":
        return texts, engine, angles
    for i, t in enumerate(texts):
        if t is None or quality(t) >= GOOD_QUALITY:
            continue
        best = (quality(t), t, 0)
        for turns, angle in ((3, 90), (1, 270), (2, 180)):  # np.rot90 turns counter-clockwise
            alt, _ = recognize([_turn(pngs[i], turns)], mode)
            if alt[0] is not None and quality(alt[0]) > best[0]:
                best = (quality(alt[0]), alt[0], angle)
            if best[0] >= GOOD_QUALITY:
                break
        texts[i], angles[i] = best[1], best[2]
    return texts, engine, angles
