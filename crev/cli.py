"""Command line: run | eval | monitor | serve | audit."""
import argparse
import json
import sys
from pathlib import Path

from . import audit, evals, monitor, pipeline, render, report

ROOT = Path(__file__).resolve().parents[1]


def _common(p):
    p.add_argument("--case", default=None, help="suite case (core or hard); eval defaults to all cases, run to core")
    p.add_argument("--mode", default="pipeline", choices=["pipeline", "agent"],
                   help="pipeline = one fixed check per requirement; agent = tool-using loop with a step trace")
    p.add_argument("--policy", default="scripted", choices=["scripted", "llm"], help="agent policy (llm needs CR_LLM_URL)")
    p.add_argument("--provider", default="heuristic", choices=["heuristic", "llm"], help="judgement provider in pipeline mode")
    p.add_argument("--chunker", default=None, help="chunking policy (v1 default, v2 = merged windows)")
    p.add_argument("--ocr", default="auto", choices=["auto", "tesseract", "node", "none"])


def _run_case(case, args):
    return pipeline.run(case["data"], case["requirements"], provider=args.provider, chunker=args.chunker, ocr_mode=args.ocr,
                        mode=args.mode, policy=args.policy, title=case.get("title"))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="crev")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="review one technical file and write its report.html")
    _common(r)
    r.add_argument("--out", default=None, help="output directory (default out, or out/<case> for other cases)")
    e = sub.add_parser("eval", help="score against the gold sets and compare with the baseline")
    _common(e)
    e.add_argument("--update-baseline", action="store_true")
    e.add_argument("--json", action="store_true")
    e.add_argument("--html", nargs="?", const=str(ROOT / "out" / "eval.html"), default=None, help="also write an HTML results page")
    e.add_argument("--label", default="", help="name for this run in the monitoring history")
    e.add_argument("--no-history", action="store_true", help="do not append to the monitoring history")
    e.add_argument("--history", default=None, help="history file (default out/history.jsonl or $CR_HISTORY)")
    m = sub.add_parser("monitor", help="render the monitoring dashboard from the run history; exit 1 if the latest run alerts")
    m.add_argument("--history", default=None)
    m.add_argument("--out", default=str(ROOT / "out"))
    s = sub.add_parser("serve", help="serve the report; reviewer decisions go to out/audit.jsonl")
    s.add_argument("--out", default=str(ROOT / "out"))
    s.add_argument("--port", type=int, default=8765)
    a = sub.add_parser("audit", help="print and verify the audit log")
    a.add_argument("--out", default=str(ROOT / "out"))
    args = ap.parse_args(argv)

    suite = {c["name"]: c for c in pipeline.load_suite()}
    if args.cmd in ("run", "eval") and args.case and args.case not in suite:
        ap.error(f"unknown case {args.case!r}; choose from {', '.join(suite)}")

    if args.cmd == "run":
        case = suite[args.case or "core"]
        run = _run_case(case, args)
        out = args.out or str(ROOT / "out" / ("" if case["name"] == "core" else case["name"]))
        path = report.build(run, out, case["data"])
        counts = {}
        for x in run["results"]:
            counts[x["verdict"]] = counts.get(x["verdict"], 0) + 1
        steps = f", {run['meta']['steps']} tool calls" if args.mode == "agent" else ""
        print(f"reviewed {len(run['results'])} requirements in {run['meta']['seconds']}s{steps}: {counts}")
        print(f"report: {path}")
        return 0
    if args.cmd == "eval":
        cases = [suite[args.case]] if args.case else list(suite.values())
        ev = evals.evaluate_suite([(c, _run_case(c, args)) for c in cases])
        if args.update_baseline:
            evals.save_baseline(ev)
            print(evals.format_report(ev))
            print("baseline written to eval/baseline.json")
            return 0
        base = evals.load_baseline()
        cmp = evals.compare(ev, base) if base and not args.case else None
        print(json.dumps(ev, indent=2) if args.json else evals.format_report(ev, cmp))
        if args.html:
            render.build(ev, cmp, args.html, args.label)
            print(f"results page: {args.html}")
        if not args.no_history:
            hp = monitor.history_path() if not args.history else Path(args.history)
            monitor.append(monitor.make_record(ev, cmp, args.label), hp)
        return 0 if (cmp is None or cmp["ok"]) else 1
    if args.cmd == "monitor":
        hp = Path(args.history) if args.history else monitor.history_path(args.out)
        hist = monitor.read(hp)
        if not hist:
            print("no history yet: run `python -m crev eval` first")
            return 2
        base = evals.load_baseline()
        score = base["passed"] / base["total"] if base else None
        alerts = monitor.build(hist, Path(args.out) / "monitor.html", score)
        for sev, code, msg in alerts:
            print(f"{sev.upper():8} {code}: {msg}")
        print(f"{len(hist)} runs; dashboard: {Path(args.out) / 'monitor.html'}")
        return 1 if any(x[0] == "critical" for x in alerts) else 0
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
