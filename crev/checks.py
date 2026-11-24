"""Deterministic checks. Each returns a Result built from verbatim quotes.

Numbers are parsed into Decimal and normalised to SI base units, so that
"0.25 GOhm" and "250 MOhm" compare as equal, and a value is never trusted
just because a neighbouring "Pass" cell says so.
"""
import re
from decimal import Decimal as D

from .model import INSUFFICIENT, MET, NOT_MET, Evidence, Result

UNITS = {
    "GOhm": ("ohm", D("1e9")), "MOhm": ("ohm", D("1e6")), "kOhm": ("ohm", D("1e3")), "Ohm": ("ohm", D(1)),
    "kV": ("volt", D(1000)), "V": ("volt", D(1)), "mV": ("volt", D("0.001")),
    "Hz": ("hertz", D(1)), "A": ("ampere", D(1)), "mA": ("ampere", D("0.001")),
    "K": ("kelvin", D(1)), "s": ("second", D(1)), "ms": ("second", D("0.001")),
    "kW": ("watt", D(1000)), "W": ("watt", D(1)),
    "uA": ("ampere", D("1e-6")), "kHz": ("hertz", D(1000)),
    "dB": ("decibel", D(1)), "%": ("percent", D(1)),
}
_ALIASES = {"Ω": "Ohm", "Ω": "Ohm", "µA": "uA", "μA": "uA"}
QTY = re.compile(r"(?P<num>[-+]?\d+(?:\.\d+)?)\s*(?P<unit>[GMk]?(?:Ohm|Ω|Ω)|kV|mV|V|kHz|Hz|[µμu]A|mA|A|kW|W|K|ms|s|dB|%)(?![A-Za-z])")
OPS = {"<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b, "<": lambda a, b: a < b, ">": lambda a, b: a > b}


def _unit_key(u):
    for sym, name in _ALIASES.items():
        u = u.replace(sym, name)
    return u


_DEC_COMMA = re.compile(r"(?<![\d.,])(\d+),(\d+)(?![\d,])")


def _fix_commas(m):
    whole, frac = m.group(1), m.group(2)
    if len(frac) == 3 and whole != "0" and len(whole) <= 3:  # 1,500 -> thousands separator
        return whole + frac
    return whole + "." + frac  # 0,62 / 12,5 -> decimal comma


def parse_quantity(text, family=None):
    """First quantity in text (optionally of a given family) -> (base_value, family, unit, raw) or None.

    Decimal commas are read as decimals ("0,62 mA"); "1,500 V" is read as a thousands separator."""
    text = _DEC_COMMA.sub(_fix_commas, text)
    for m in QTY.finditer(text):
        unit = _unit_key(m["unit"])
        if unit not in UNITS:
            continue
        fam, factor = UNITS[unit]
        if family is None or fam == family:
            return D(m["num"]) * factor, fam, unit, m.group(0)
    return None


def clip(line, start=0, width=200):
    line = line.strip()
    if len(line) <= width:
        return line
    s = max(0, start - width // 3)
    return line[s:s + width].strip()


def _lines(chunk):
    return [l for l in chunk.text.splitlines() if l.strip()]


def _ev(chunk, quote):
    return Evidence(chunk.doc, chunk.page, quote, chunk.id, chunk.kind)


def find_rows(corpus, doc, label, kinds=None):
    """Yield (chunk, line, rest_of_line) for lines whose label matches.

    Table rows match on the first cell; prose lines match anywhere. Only the
    first occurrence per line is used.
    """
    rx = re.compile(label, re.I)
    for c in corpus.chunks(doc):
        if kinds and c.kind not in kinds:
            continue
        for line in _lines(c):
            if c.kind == "table":
                cells = [x.strip() for x in line.split("|")]
                if rx.search(cells[0]):
                    yield c, line, " ".join(cells[1:])
            else:
                m = rx.search(line)
                if m:
                    yield c, line, line[m.end():]


def ocr_diag(corpus, doc):
    info = corpus.docs.get(doc)
    return ["OCR_UNAVAILABLE"] if info and info.ocr_failed else []


def consistency(req, corpus, provider=None):
    """All sources must report the same value (numbers compared after unit normalisation)."""
    found, diags, missing = [], [], []
    for src in req["sources"]:
        hit = None
        for c, line, rest in find_rows(corpus, src["doc"], src["label"], src.get("kinds")):
            if "capture" in src:
                m = re.search(src["capture"], line)
                if m:
                    hit = (c, line, m.group(0).strip().lower(), m.group(0))
            else:
                q = parse_quantity(rest, src.get("family"))
                if q:
                    hit = (c, line, q[0], q[3])
            if hit:
                break
        if hit:
            found.append((src, hit))
        else:
            missing.append(src)
            diags.append(f"NO_MATCH:{src['doc']}")
            if src.get("kinds") == ["ocr"] or "ocr" in (src.get("kinds") or []):
                diags += ocr_diag(corpus, src["doc"]) or ["OCR_NO_MATCH"]
    ev = [_ev(c, clip(line)) for _, (c, line, _, _) in found]
    if missing:
        return Result(req["id"], req["text"], INSUFFICIENT, ev,
                      f"No value found in {len(missing)} of {len(req['sources'])} sources.", diags, "consistency")
    values = {v for _, (_, _, v, _) in found}
    shown = "; ".join(f"{raw} ({c.doc} p{c.page})" for _, (c, _, _, raw) in found)
    if len(values) == 1:
        return Result(req["id"], req["text"], MET, ev, f"Values agree: {shown}.", diags, "consistency")
    return Result(req["id"], req["text"], NOT_MET, ev, f"Values disagree: {shown}.", diags, "consistency")


def limit(req, corpus, provider=None):
    """Every matching table row must satisfy `op limit`; the measured value is recomputed, not read from a Result column."""
    lim = parse_quantity(req["limit"])
    fam, op = lim[1], OPS[req["op"]]
    rows, diags = [], []
    for c, line, rest in find_rows(corpus, req["doc"], req["row"], req.get("kinds")):
        q = parse_quantity(rest)
        if q is None:
            continue
        if q[1] != fam:
            diags.append("UNIT_UNRESOLVED")
            continue
        rows.append((c, line, q))
    if any(r[0].kind == "table" for r in rows):  # a results table outranks a prose mention of the same quantity
        rows = [r for r in rows if r[0].kind == "table"]
    if not rows:
        return Result(req["id"], req["text"], INSUFFICIENT, [], "No matching measurement row found.",
                      diags + ["NO_ROW"], "limit")
    bad = [r for r in rows if not op(r[2][0], lim[0])]
    pick = bad or rows
    ev = [_ev(c, clip(line)) for c, line, _ in pick]
    if bad:
        c, line, q = bad[0]
        return Result(req["id"], req["text"], NOT_MET, ev,
                      f"{q[3]} violates {req['op']} {lim[3]} (p{c.page}).", diags, "limit")
    return Result(req["id"], req["text"], MET, ev,
                  f"All {len(rows)} row(s) satisfy {req['op']} {lim[3]}.", diags, "limit")


def evidence_present(req, corpus, provider=None):
    """Every pattern must be found in the named documents; contradicting patterns make it not met."""
    ev, miss = [], []
    for pat in req["patterns"]:
        rx = re.compile(pat, re.I)
        hit = None
        for doc in req["docs"]:
            for c in corpus.chunks(doc):
                for line in _lines(c):
                    m = rx.search(line)
                    if m:
                        hit = _ev(c, clip(line, m.start()))
                        break
                if hit:
                    break
            if hit:
                break
        (ev if hit else miss).append(hit or pat)
    if miss:
        return Result(req["id"], req["text"], INSUFFICIENT, ev, f"Not found: {len(miss)} of {len(req['patterns'])} expected statements.",
                      ["NO_MATCH"], "evidence_present")
    return Result(req["id"], req["text"], MET, ev, "All expected statements found.", [], "evidence_present")


def risk_table(req, corpus, provider=None):
    """Rows rated High residual risk must carry a completed verification reference."""
    bad, seen = [], 0
    for c in corpus.chunks(req["doc"]):
        if c.kind != "table":
            continue
        for line in _lines(c):
            cells = [x.strip() for x in line.split("|")]
            if len(cells) >= 6 and re.fullmatch(r"H-\d+", cells[0]):
                seen += 1
                if cells[4].lower() == "high" and not re.fullmatch(r"V-\d+", cells[5]):
                    bad.append((c, line))
    if not seen:
        return Result(req["id"], req["text"], INSUFFICIENT, [], "No hazard register found.", ["NO_ROW"], "risk_table")
    if bad:
        return Result(req["id"], req["text"], NOT_MET, [_ev(c, clip(l)) for c, l in bad],
                      f"{len(bad)} hazard(s) with High residual risk lack completed verification.", [], "risk_table")
    return Result(req["id"], req["text"], MET, [], f"All {seen} hazards checked; none with unverified High residual risk.", [], "risk_table")


def semantic(req, corpus, provider):
    """Free-text judgement: retrieve candidates, then ask the provider."""
    from .providers import retrieve
    cands = retrieve(corpus, req["docs"], req["retrieve"])
    if not cands:
        return Result(req["id"], req["text"], INSUFFICIENT, [], "No relevant passage retrieved.", ["NO_MATCH"], "semantic")
    j = provider.judge(req, cands)
    ev = [Evidence(j.chunk.doc, j.chunk.page, j.quote, j.chunk.id, j.chunk.kind)] if j.chunk else []
    return Result(req["id"], req["text"], j.verdict, ev, j.rationale, list(j.diagnostics), f"semantic:{provider.name}")


CHECKS = {"consistency": consistency, "limit": limit, "evidence_present": evidence_present,
          "risk_table": risk_table, "semantic": semantic}
