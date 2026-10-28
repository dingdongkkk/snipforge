"""Command-line interface (non-interactive: ambiguities are auto-resolved into recorded assumptions).

    python cli.py "Implement shipping_fee(total, express) ..." --provider groq --zip out.zip
"""
from __future__ import annotations

import argparse
import sys

from snipforge import reporting
from snipforge.config import DEFAULT_PROVIDER, MAX_REPAIRS, PROVIDERS
from snipforge.pipeline import PipelineError, analyze, run_generation


def main() -> int:
    ap = argparse.ArgumentParser(description="SnipForge: requirement -> Python function with test evidence")
    ap.add_argument("requirement", nargs="?", help="feature requirement (or pipe via stdin)")
    ap.add_argument("--provider", default=DEFAULT_PROVIDER, choices=list(PROVIDERS))
    ap.add_argument("--model", default=None)
    ap.add_argument("--function-name", default=None)
    ap.add_argument("--max-repairs", type=int, default=MAX_REPAIRS)
    ap.add_argument("--zip", help="write the export bundle to this path")
    args = ap.parse_args()
    req = args.requirement or sys.stdin.read()

    try:
        a = analyze(req, args.provider, args.model, function_name=args.function_name, auto_resolve=True)
    except PipelineError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    ct = a["contract"]
    print(f"[contract] {ct['function_name']}: " + "; ".join(f"{r['id']} {r['text']}" for r in ct["requirements"]),
          file=sys.stderr)
    result = None
    for ev in run_generation(ct, args.provider, args.model, max_repairs=args.max_repairs):
        if ev["type"] == "error":
            print(f"error: {ev['message']}", file=sys.stderr)
            return 1
        if ev["type"] == "stage" and ev["status"] != "running":
            d = ev.get("data", {})
            extra = f" {d['counts']['pass']}/{len(d['results'])} cases pass ({d['status']})" if ev["stage"] == "validate" else ""
            print(f"[{ev['stage']:>8}] {ev['status']}{extra}", file=sys.stderr)
        if ev["type"] == "result":
            result = ev
    print(result["code"])
    for e in result["evidence"]:
        print(f"  {e['requirement_id']} {e['outcome']:<12} {', '.join(e['cases']) or '-'}  {e['text']}", file=sys.stderr)
    print(f"# status={result['status']} model_calls={result['model_calls']} run={reporting.save_run(result)}",
          file=sys.stderr)
    if args.zip:
        with open(args.zip, "wb") as fh:
            fh.write(reporting.bundle(result))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    sys.exit(main())
