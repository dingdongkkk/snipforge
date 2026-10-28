"""Working with a finished run: challenge it, capture regressions, revise its requirements.

Every operation is bounded (one challenge call; revision = 1 contract call + 1 test-design call
+ 1 code call + repairs) and runs code only through the isolated runner. Operations that change
code or tests produce a NEW run version linked to its parent; the parent is never modified except
to attach challenge results.
"""
from __future__ import annotations

import time
from typing import Iterator

from . import prompts
from .config import MAX_REPAIRS, TOP_K_EXAMPLES
from .contracts import (ContractError, input_key, next_case_number, normalize_contract, stable_hash,
                        validate_cases)
from .llm import LLMError
from .pipeline import (PipelineError, _build_result, _client, _json_call, _unified, _verify_repair,
                       designer_info, get_retriever, test_client)
from .retriever import normalize_text
from .runner import execute_cases, execution_mode

MAX_CHALLENGE_CASES = 10


# ---------------------------------------------------------------- 1. challenge this snippet

def challenge(run: dict, provider: str, model: str | None = None, client=None, test_provider: str | None = None,
              test_model: str | None = None) -> dict:
    """Ask for adversarial, contract-derived cases (contract only, never the code) and run them."""
    if run["validation"]["execution_mode"] == "not_executed":
        raise PipelineError("This run's code was not executed, so it cannot be challenged.")
    t0 = time.time()
    main = _client(provider, model, client)
    c = test_client(main, provider, model, test_provider, test_model, client)  # attacker = test designer
    contract, frozen = run["contract"], run["test_cases"]
    try:
        raw, _, calls = _json_call(c, prompts.challenge_messages(contract, frozen), 3000)
    except LLMError as e:
        raise PipelineError(f"Challenge call failed: {e}") from e
    cases, rejected = validate_cases(raw if raw is not None else [], contract, prefix="C")
    known = {input_key(t) for t in frozen}
    fresh = [x for x in cases if input_key(x) not in known]
    rejected += [f"{x['id']}: already covered by a frozen test" for x in cases if input_key(x) in known]
    fresh = fresh[:MAX_CHALLENGE_CASES]
    run_out = execute_cases(run["code"], contract["function_name"], fresh, mode=execution_mode())
    by_id = {r["test_id"]: r for r in run_out["results"]}
    req_text = {r["id"]: r["text"] for r in contract["requirements"]}
    findings = [{"case": x, "result": by_id[x["id"]],
                 "requirements": [{"id": rid, "text": req_text[rid]} for rid in x["requirement_ids"]]}
                for x in fresh if by_id[x["id"]]["status"] in ("fail", "error", "timeout")]
    counts = {s: sum(r["status"] == s for r in run_out["results"]) for s in ("pass", "fail", "error", "timeout")}
    return {"cases": fresh, "results": run_out["results"], "rejected": rejected, "findings": findings,
            "counts": counts, "execution_mode": run_out["mode"], "model_calls": calls,
            "latency_s": round(time.time() - t0, 2), **designer_info(main, c, provider, model, test_provider)}


# ---------------------------------------------------------------- shared: new version of a run

def _child(parent: dict, parent_id: str, result: dict, **extra) -> dict:
    result.update(version=parent.get("version", 1) + 1, parent_run_id=parent_id,
                  version_diff=_unified(parent["code"], result["code"], f"v{parent.get('version', 1)}.py",
                                        f"v{parent.get('version', 1) + 1}.py"), **extra)
    return result


def regress(run: dict, run_id: str, case_ids: list[str], provider: str, model: str | None = None,
            max_repairs: int = MAX_REPAIRS, client=None) -> Iterator[dict]:
    """Promote selected challenge cases to frozen regression tests, re-verify, repair code if needed."""
    t_start = time.time()
    ch = run.get("challenge") or {}
    picked = [x for x in ch.get("cases", []) if x["id"] in set(case_ids)]
    if not picked:
        yield {"type": "error", "message": "Select at least one challenge case to keep as a regression test."}
        return
    try:
        c = _client(provider, model, client)
    except PipelineError as e:
        yield {"type": "error", "message": str(e)}
        return
    n = next_case_number(run["test_cases"])
    added = [{**{k: v for k, v in x.items() if k != "id"}, "id": f"T{n + i}", "origin": f"challenge {x['id']}"}
             for i, x in enumerate(picked)]
    cases = run["test_cases"] + added
    test_set_hash = stable_hash(cases)
    yield {"type": "stage", "stage": "tests", "status": "done",
           "data": {"state": "tests_ready", "test_cases": cases, "rejected": [], "test_set_hash": test_set_hash,
                    "evidence": []}}
    timings, counter = {}, {"calls": 0}
    try:
        attempts = yield from _verify_repair(run["contract"], cases, run["code"], c, execution_mode(),
                                             max_repairs, timings, counter)
    except PipelineError as e:
        yield {"type": "error", "message": str(e)}
        return
    res = _build_result(provider=provider, c=c, model=model, contract=run["contract"], cases=cases, rejected=[],
                        attempts=attempts, gen={"explanation": run.get("explanation", ""),
                                            "limitations": run.get("limitations", [])},
                        examples=[], test_set_hash=test_set_hash, calls=counter["calls"], timings=timings,
                        t_start=t_start)
    yield _child(run, run_id, res, change=f"Added {len(added)} regression test(s) from the challenge",
                 test_changes={"kept": [t["id"] for t in run["test_cases"]], "removed": [],
                               "added": [t["id"] for t in added]})


# ---------------------------------------------------------------- 2. requirement revisions

def _norm(text: str) -> str:
    return normalize_text(text).rstrip(".")


def propose_revision(run: dict, change: str, provider: str, model: str | None = None, client=None,
                     answers: list[dict] | None = None) -> dict:
    """One model call -> revised contract + per-requirement diff (unchanged / modified / added / removed).

    `answers` to the model's multiple-choice questions are folded into the change request.
    """
    change = (change or "").strip()
    if not change:
        raise PipelineError("Describe the change")
    answered = [a for a in (answers or []) if a.get("answer")]
    if answered:
        change += "\nClarifications: " + "; ".join(f"{a['question']} -> {a['answer']}" for a in answered)
    old = run["contract"]
    c = _client(provider, model, client)
    try:
        raw, _, calls = _json_call(c, prompts.revise_contract_messages(old, change), 1500)
    except LLMError as e:
        raise PipelineError(f"Revision call failed: {e}") from e
    if not isinstance(raw, dict):
        raise PipelineError("Model returned an unusable revised contract; retry or rephrase.")
    old_by_id = {r["id"]: r["text"] for r in old["requirements"]}
    old_by_text = {_norm(t): i for i, t in old_by_id.items()}
    used, reqs, next_n = set(), [], max(int(i[1:]) for i in old_by_id) + 1
    for r in raw.get("requirements") or []:
        text = (r.get("text") if isinstance(r, dict) else r) or ""
        if not str(text).strip():
            continue
        src = r.get("source_id") if isinstance(r, dict) else None
        rid = src if src in old_by_id and src not in used else old_by_text.get(_norm(text))
        if rid is None or rid in used:
            rid, next_n = f"R{next_n}", next_n + 1
        used.add(rid)
        reqs.append({"id": rid, "text": str(text).strip()})
    try:
        new = normalize_contract({**raw, "requirements": reqs, "function_name": raw.get("function_name") or
                                  old["function_name"]}, f"{old['raw_requirement']}\n\nRevision: {change}",
                                 examples=old.get("examples") or [],
                                 request_id=old.get("request_id"))
    except ContractError as e:
        raise PipelineError(f"Revised contract is invalid: {e}") from e
    diff = []
    for r in new["requirements"]:
        if r["id"] not in old_by_id:
            status = "added"
        elif _norm(old_by_id[r["id"]]) == _norm(r["text"]):
            status = "unchanged"
        else:
            status = "modified"
        diff.append({"id": r["id"], "text": r["text"], "status": status, "before": old_by_id.get(r["id"])})
    removed = [{"id": i, "text": t, "status": "removed"} for i, t in old_by_id.items() if i not in used]
    state = "needs_clarification" if new["clarification_questions"] else "contract_ready"
    return {"state": state, "contract": new, "requirement_diff": diff + removed, "change": change,
            "model_calls": calls}


def run_revision(run: dict, run_id: str, contract: dict, change: str, provider: str, model: str | None = None,
                 max_repairs: int = MAX_REPAIRS, client=None, test_provider: str | None = None,
                 test_model: str | None = None) -> Iterator[dict]:
    """Version contract, tests and code together. Unaffected tests are kept as regression checks."""
    t_start = time.time()
    timings, counter = {}, {"calls": 0}
    try:
        contract = normalize_contract(contract, contract.get("raw_requirement", ""), contract.get("function_name"),
                                      contract.get("examples") or [], contract.get("request_id"))
        c = _client(provider, model, client)
        tc = test_client(c, provider, model, test_provider, test_model, client)
    except (ContractError, PipelineError) as e:
        yield {"type": "error", "message": str(e)}
        return
    designer = designer_info(c, tc, provider, model, test_provider)
    old_by_id = {r["id"]: _norm(r["text"]) for r in run["contract"]["requirements"]}
    unchanged = {r["id"] for r in contract["requirements"] if old_by_id.get(r["id"]) == _norm(r["text"])}
    affected = [r["id"] for r in contract["requirements"] if r["id"] not in unchanged]
    if not affected and contract["function_name"] == run["contract"]["function_name"] and \
            {r["id"] for r in contract["requirements"]} == set(old_by_id):
        yield {"type": "error", "message": "The revised contract is identical to the current one."}
        return
    kept = [t for t in run["test_cases"] if set(t["requirement_ids"]) <= unchanged]
    removed = [t["id"] for t in run["test_cases"] if t not in kept]

    t = time.time()
    yield {"type": "stage", "stage": "tests", "status": "running"}
    new_cases, rejected = [], []
    if affected:
        try:
            raw, _, n = _json_call(tc, prompts.test_design_messages(contract, only_ids=affected, existing=kept), 3000)
            counter["calls"] += n
        except LLMError as e:
            yield {"type": "error", "message": f"Test design failed: {e}"}
            return
        new_cases, rejected = validate_cases(raw if raw is not None else [], contract,
                                             start=next_case_number(run["test_cases"]), allowed_ids=set(affected))
        known = {input_key(k) for k in kept}
        rejected += [f"{x['id']}: same input as a kept test" for x in new_cases if input_key(x) in known]
        new_cases = [x for x in new_cases if input_key(x) not in known]
    cases = kept + new_cases
    test_set_hash = stable_hash(cases)
    timings["tests"] = round(time.time() - t, 2)
    test_changes = {"kept": [x["id"] for x in kept], "removed": removed, "added": [x["id"] for x in new_cases]}
    yield {"type": "stage", "stage": "tests", "status": "done" if cases else "failed",
           "data": {"state": "tests_ready", "test_cases": cases, "rejected": rejected, "test_set_hash": test_set_hash,
                    "test_changes": test_changes, "evidence": []}}

    t = time.time()
    yield {"type": "stage", "stage": "generate", "status": "running"}
    examples = get_retriever().search(normalize_text(change + " " + contract["function_name"]), k=TOP_K_EXAMPLES)
    try:
        gen = prompts.parse_generation(c.chat(prompts.revise_code_messages(contract, run["code"], change, examples),
                                              temperature=0.2))
        counter["calls"] += 1
    except LLMError as e:
        yield {"type": "error", "message": f"Generation failed: {e}"}
        return
    timings["generate"] = round(time.time() - t, 2)
    yield {"type": "stage", "stage": "generate", "status": "done", "data": {"state": "generated", **gen}}

    try:
        attempts = yield from _verify_repair(contract, cases, gen["code"], c, execution_mode(), max_repairs,
                                             timings, counter)
    except PipelineError as e:
        yield {"type": "error", "message": str(e)}
        return
    res = _build_result(provider=provider, c=c, model=model, contract=contract, cases=cases, rejected=rejected,
                        attempts=attempts, gen=gen, examples=examples, test_set_hash=test_set_hash,
                        calls=counter["calls"], timings=timings, t_start=t_start, test_designer=designer)
    final = {r["test_id"]: r["status"] for r in res["validation"]["results"]}
    regression = {"total": len(kept), "pass": sum(final.get(x["id"]) == "pass" for x in kept)}
    yield _child(run, run_id, res, change=change, test_changes=test_changes, regression=regression,
                 contract_diff=[{"id": r["id"], "status": "unchanged" if r["id"] in unchanged else
                                 ("modified" if r["id"] in old_by_id else "added"), "text": r["text"]}
                                for r in contract["requirements"]] +
                               [{"id": i, "status": "removed", "text": tx["text"]} for i, tx in
                                ((r["id"], r) for r in run["contract"]["requirements"])
                                if i not in {r["id"] for r in contract["requirements"]}])
