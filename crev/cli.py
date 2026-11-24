"""Command line: run | eval | serve | audit."""
import argparse
import json
import sys
from pathlib import Path

from . import audit, evals, pipeline, report

ROOT = Path(__file__).resolve().parents[1]


def _common(p):
    p.add_argument("--data", default=str(pipeline.DATA / "techfile"), help="directory with the PDFs")
    p.add_argument("--provider", default="heuristic", choices=["heuristic", "llm"])
    p.add_argument("--chunker", default=None, help="chunking policy (v1 default, v2 = merged windows)")
    p.add_argument("--ocr", default="auto", choices=["auto", "tesseract", "node", "none"])


def main(argv=None):
    ap = argparse.ArgumentParser(prog="crev")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="review the technical file and write out/report.html")
    _common(r)
    r.add_argument("--out", default=str(ROOT / "out"))
    e = sub.add_parser("eval", help="score against the gold set and compare with the baseline")
    _common(e)
    e.add_argument("--update-baseline", action="store_true")
    e.add_argument("--json", action="store_true")
    s = sub.add_parser("serve", help="serve the report; reviewer decisions go to out/audit.jsonl")
    s.add_argument("--out", default=str(ROOT / "out"))
    s.add_argument("--port", type=int, default=8765)
    a = sub.add_parser("audit", help="print and verify the audit log")
    a.add_argument("--out", default=str(ROOT / "out"))
    args = ap.parse_args(argv)

    if args.cmd == "run":
        run = pipeline.run(args.data, provider=args.provider, chunker=args.chunker, ocr_mode=args.ocr)
        path = report.build(run, args.out, args.data)
        counts = {}
        for x in run["results"]:
            counts[x["verdict"]] = counts.get(x["verdict"], 0) + 1
        print(f"reviewed {len(run['results'])} requirements: {counts}")
        print(f"report: {path}")
        return 0
    if args.cmd == "eval":
        run = pipeline.run(args.data, provider=args.provider, chunker=args.chunker, ocr_mode=args.ocr)
        ev = evals.evaluate(run)
        if args.update_baseline:
            evals.save_baseline(ev)
            print(evals.format_report(ev))
            print("baseline written to eval/baseline.json")
            return 0
        base = evals.load_baseline()
        cmp = evals.compare(ev, base) if base else None
        print(json.dumps(ev, indent=2) if args.json else evals.format_report(ev, cmp))
        return 0 if (cmp is None or cmp["ok"]) else 1
    if args.cmd == "serve":
        srv = report.serve(args.out, args.port)
        print(f"http://localhost:{args.port}/  (Ctrl-C to stop)")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    if args.cmd == "audit":
        p = Path(args.out) / "audit.jsonl"
        for x in audit.read(p):
            print(f"{x['ts']} {x['req_id']} system={x['system_verdict']} {x['decision']} -> {x['final_verdict']} by {x['reviewer']} {x['note']}")
        ok, bad = audit.verify(p)
        print("chain ok" if ok else f"CHAIN BROKEN at entry {bad}")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
