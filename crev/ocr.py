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
