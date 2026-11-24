"""Append-only reviewer audit log (JSON lines) with a hash chain.

Each line stores the hash of the previous line, so editing or deleting an
earlier entry is detectable with verify(). This is tamper-evident, not
tamper-proof: someone who can rewrite the whole file can recompute it.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .model import VERDICTS

DECISIONS = ("accept", "override")


def _hash(entry):
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read(path):
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def append(path, run, req_id, decision, reviewer="reviewer", final_verdict=None, note=""):
    results = {r["req_id"]: r for r in run["results"]}
    if req_id not in results:
        raise ValueError(f"unknown requirement {req_id!r}")
    if decision not in DECISIONS:
        raise ValueError("decision must be accept or override")
    system = results[req_id]["verdict"]
    if decision == "override":
        if final_verdict not in VERDICTS:
            raise ValueError("override needs a final verdict")
        if not note.strip():
            raise ValueError("override needs a note explaining why")
    else:
        final_verdict = system
    prev = read(path)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_id": run["run_id"], "req_id": req_id, "system_verdict": system,
        "decision": decision, "final_verdict": final_verdict,
        "reviewer": (reviewer or "reviewer")[:80], "note": note[:2000],
        "evidence": [f"{e['doc']} p{e['page']}" for e in results[req_id]["evidence"]],
        "prev": prev[-1]["hash"] if prev else "",
    }
    entry["hash"] = _hash(entry)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def verify(path):
    """Return (ok, index_of_first_bad_line or None)."""
    prev = ""
    for i, e in enumerate(read(path)):
        if e.get("prev") != prev or e.get("hash") != _hash(e):
            return False, i
        prev = e["hash"]
    return True, None
