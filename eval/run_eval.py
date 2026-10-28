"""Evaluation: direct-prompt baseline vs. full pipeline on the SAME frozen tasks, model and hidden tests.

    python eval/run_eval.py --provider groq                     # both modes on the 20-task holdout
    python eval/run_eval.py --provider groq --set dev           # tune prompts on the dev set only
    python eval/run_eval.py --provider ollama --mode pipeline --limit 5

Integrity rules
  * Hidden tests never enter prompts, retrieval or repair. The pipeline repairs only from its OWN
    contract-derived tests.
  * The pipeline uses more model calls than the baseline; calls and latency are reported side by side.
  * Once the holdout has been used to tune prompts it is no longer untouched. Say so when reporting.

Functional success = tasks whose code passes ALL hidden tests / total tasks (target >= 16/20).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from snipforge.llm import LLMClient  # noqa: E402
from snipforge.pipeline import PipelineError, direct_baseline, run_full  # noqa: E402
from snipforge.validator import check_syntax, run_tests  # noqa: E402

SETS = {"holdout": ROOT / "data" / "benchmark.jsonl", "dev": ROOT / "data" / "development.jsonl"}


def hidden(code: str, tests: str) -> dict:
    r = run_tests(code, tests)
    return {"pass": r["total"] > 0 and r["passed"] == r["total"], "passed": r["passed"], "total": r["total"]}


def eval_task(task: dict, mode: str, provider: str, model: str | None, test_provider: str | None = None,
              test_model: str | None = None, spec_by_tester: bool = False, small: bool = False) -> dict:
    t0 = time.time()
    client = LLMClient(provider, model)
    try:
        if mode == "baseline":
            out = direct_baseline(task["requirement"], provider, model, client=client)
            code, first_code, calls, attempts = out["code"], out["code"], out["model_calls"], 1
        else:
            out = run_full(task["requirement"], provider, model, client=client, test_provider=test_provider or "",
                           test_model=test_model or "", spec_by_tester=spec_by_tester,
                           trust_own_tests=False if small else None)
            if out.get("type") != "result":
                raise PipelineError(out.get("message", "pipeline error"))
            code, first_code = out["code"], out["original_code"]
            calls, attempts = out["model_calls"], len(out["attempts"])
    except Exception as e:  # count as a failed task, never drop it
        return {"id": task["id"], "category": task.get("category"), "mode": mode, "error": str(e)[:300],
                "syntax_ok": False, "first_pass": False, "final_pass": False, "hidden_passed": 0, "hidden_total": 0,
                "model_calls": 0, "attempts": 0, "latency_s": round(time.time() - t0, 2)}
    first, final = hidden(first_code, task["hidden_tests"]), hidden(code, task["hidden_tests"])
    return {"id": task["id"], "category": task.get("category"), "mode": mode,
            "syntax_ok": check_syntax(code)["ok"], "first_pass": first["pass"], "final_pass": final["pass"],
            "hidden_passed": final["passed"], "hidden_total": final["total"],
            "self_status": out.get("status") if mode == "pipeline" else None,
            "model_calls": calls, "attempts": attempts, "latency_s": round(time.time() - t0, 2)}


def summarize(rows: list[dict]) -> dict:
    n = len(rows) or 1
    cats: dict = {}
    for r in rows:
        c = cats.setdefault(r["category"] or "-", [0, 0])
        c[0] += r["final_pass"]; c[1] += 1
    return {
        "tasks": len(rows),
        "functional_success": f"{sum(r['final_pass'] for r in rows)}/{len(rows)}",
        "functional_success_%": round(100 * sum(r["final_pass"] for r in rows) / n, 1),
        "first_attempt_%": round(100 * sum(r["first_pass"] for r in rows) / n, 1),
        "syntax_valid_%": round(100 * sum(r["syntax_ok"] for r in rows) / n, 1),
        "hidden_assertion_rate_%": round(100 * sum(r["hidden_passed"] for r in rows)
                                         / max(sum(r["hidden_total"] for r in rows), 1), 1),
        "avg_model_calls": round(sum(r["model_calls"] for r in rows) / n, 2),
        "avg_latency_s": round(sum(r["latency_s"] for r in rows) / n, 2),
        "errors": sum("error" in r for r in rows),
        "by_category": {k: f"{v[0]}/{v[1]}" for k, v in cats.items()},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True)
    ap.add_argument("--model", default=None)
    ap.add_argument("--set", choices=list(SETS), default="holdout")
    ap.add_argument("--mode", choices=["both", "baseline", "pipeline"], default="both")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--test-provider", default=None, help="independent model designs the pipeline's tests")
    ap.add_argument("--test-model", default=None)
    ap.add_argument("--spec-by-tester", action="store_true", help="test model also writes the contract (architect/coder)")
    ap.add_argument("--small-model-mode", action="store_true",
                    help="same-model tests are evidence only: no repair, code chosen by agreement")
    args = ap.parse_args()

    tasks = [json.loads(l) for l in SETS[args.set].read_text().splitlines() if l.strip()]
    if args.limit:
        tasks = tasks[: args.limit]
    modes = ["baseline", "pipeline"] if args.mode == "both" else [args.mode]
    rows = []
    for mode in modes:
        print(f"\n== {mode} ==")
        for i, task in enumerate(tasks, 1):
            r = eval_task(task, mode, args.provider, args.model, args.test_provider, args.test_model,
                          args.spec_by_tester, args.small_model_mode)
            rows.append(r)
            mark = "PASS" if r["final_pass"] else "FAIL"
            extra = f" ERROR {r['error'][:70]}" if "error" in r else ""
            print(f"[{i:>2}/{len(tasks)}] {task['id']:<22} {mark}  hidden {r['hidden_passed']}/{r['hidden_total']}  "
                  f"first={'Y' if r['first_pass'] else 'N'} calls={r['model_calls']} {r['latency_s']}s{extra}")

    report = {"provider": args.provider, "model": args.model or "default", "set": args.set,
              "test_designer": f"{args.test_provider}/{args.test_model or 'default'}" if args.test_provider else "same",
              "contract_by": "test designer" if args.spec_by_tester else "code model",
              "small_model_mode": args.small_model_mode,
              "benchmark_version": tasks[0].get("version") if tasks else None,
              "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "summary": {m: summarize([r for r in rows if r["mode"] == m]) for m in modes}, "rows": rows}
    out_dir = ROOT / "eval" / "results"
    out_dir.mkdir(exist_ok=True)
    tag = (args.model or "default").split("/")[-1] + (f"-tests-{args.test_provider}" if args.test_provider else "") + \
        ("-spec" if args.spec_by_tester else "") + ("-small" if args.small_model_mode else "")
    path = out_dir / f"{args.set}-{args.provider}-{tag}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2))
    print("\n" + json.dumps(report["summary"], indent=2))
    if "pipeline" in report["summary"]:
        s = report["summary"]["pipeline"]
        print(f"\nPipeline functional success: {s['functional_success']} (target >= 80%: "
              f"{'met' if s['functional_success_%'] >= 80 else 'not met'})")
    print(f"Saved {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
