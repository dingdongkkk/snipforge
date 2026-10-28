"""Orchestrator with an explicit state machine.

  draft -> needs_clarification | contract_ready        (analyze: 1 model call)
        -> tests_ready   (test design from the CONTRACT ONLY, then frozen: 1 call)
        -> generated     (implementation, never sees the tests: 1 call)
        -> validated     (syntax + policy + trusted execution of the frozen cases)
        -> [repair: code only, same frozen cases, bounded]
        -> passed | failed | not_executed

The model-call budget is 3 calls plus max_repairs, plus at most one schema-recovery call per phase.
`analyze` and `run_generation` are separate so a human can confirm the contract in between.
"""
from __future__ import annotations

import ast
import difflib
import json
import re
import time
from datetime import datetime, timezone
from typing import Iterator

from . import prompts
from .config import CONSENSUS, MAX_REPAIRS, TEST_MODEL, TEST_PROVIDER, TOP_K_EXAMPLES, TRUST_OWN_TESTS
from .contracts import (ContractError, normalize_contract, requirement_evidence, stable_hash,
                        validate_cases, validate_contract)
from .llm import LLMClient, LLMError
from .retriever import Retriever, normalize_text
from .runner import execute_cases, execution_mode, values_equal
from .validator import check_syntax, policy_check

_retriever: Retriever | None = None


class PipelineError(RuntimeError):
    pass


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever


_NAMED_CALL = re.compile(r"(?<![\w.])([A-Za-z_][A-Za-z0-9_]*)\(")
_NOT_NAMES = {"e", "eg", "i", "ie", "if", "and", "or", "not", "list", "dict", "str", "int", "float", "set", "tuple"}


def explicit_function_name(requirement: str) -> str | None:
    """A name the requirement spells out as a call, e.g. 'Implement shipping_fee(total, express)'."""
    for m in _NAMED_CALL.finditer(requirement):
        if m.group(1).lower() not in _NOT_NAMES:
            return m.group(1)
    return None


def explicit_signature(requirement: str) -> tuple[str, list[dict]] | None:
    """Parse a signature the requirement spells out, e.g. 'add_gst(amount, rate=18)' -> name + parameters."""
    for m in _NAMED_CALL.finditer(requirement):
        if m.group(1).lower() in _NOT_NAMES:
            continue
        depth, i = 1, m.end()
        while i < len(requirement) and depth:
            depth += {"(": 1, ")": -1}.get(requirement[i], 0)
            i += 1
        try:
            fn = ast.parse(f"def {m.group(1)}({requirement[m.end():i - 1]}): pass").body[0]
        except SyntaxError:
            return None
        a = fn.args
        defaults = dict(zip([x.arg for x in (a.posonlyargs + a.args)][::-1], a.defaults[::-1]))
        defaults.update({x.arg: d for x, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None})
        params = [{"name": x.arg, "type": "Any",
                   "description": f"default {ast.unparse(defaults[x.arg])}" if x.arg in defaults else ""}
                  for x in a.posonlyargs + a.args + a.kwonlyargs]
        return m.group(1), params
    return None


_DECLARATION = re.compile(r"^\W*(?:please\s+)?(?:implement|write|create|define|build)?\s*(?:a\s+function\s+)?"
                          r"[A-Za-z_]\w*\([^)]*\)\s*[.:]?\s*$", re.I)


def fallback_contract(requirement: str, function_name: str | None, sig, reason: str) -> dict:
    """Deterministic contract when the model's JSON is unusable: each sentence becomes a requirement."""
    name = function_name or (sig[0] if sig else None)
    if not name:
        raise ContractError(reason)
    sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+", requirement.strip()) if x.strip()]
    reqs = [x for x in sentences if not _DECLARATION.match(x)] or sentences
    return normalize_contract({"function_name": name, "parameters": sig[1] if sig else [], "requirements": reqs,
                               "assumptions": [f"Contract taken directly from the requirement text: the model's "
                                               f"structured contract was unusable ({reason})."]},
                              requirement, name)


def _bind_signature(contract: dict, sig) -> None:
    """Parameters spelled out in the requirement are binding; invented extras are dropped (and recorded)."""
    if not sig or sig[0] != contract["function_name"]:
        return
    model_params = {p["name"]: p for p in contract["parameters"]}
    bound = [{**p, **{k: v for k, v in model_params.get(p["name"], {}).items() if v}} for p in sig[1]]
    dropped = [n for n in model_params if n not in {p["name"] for p in sig[1]}]
    contract["parameters"] = bound
    if dropped:
        contract["assumptions"].append(f"Parameters fixed to the signature in the requirement; "
                                       f"dropped invented parameter(s): {', '.join(dropped)}.")


def _client(provider: str, model: str | None, client=None):
    if client is not None:
        return client
    try:
        return LLMClient(provider, model)
    except LLMError as e:
        raise PipelineError(str(e)) from e


def test_client(main, provider: str, model: str | None, test_provider: str | None = None,
                test_model: str | None = None, client=None):
    """Client that designs tests: an explicit independent one, the configured default, or the code model itself."""
    if client is not None:
        return client
    tp = test_provider if test_provider is not None else TEST_PROVIDER
    tm = test_model if test_model is not None else (TEST_MODEL or None)
    if not tp or (tp == provider and (tm or None) == (model or None)):
        return main
    return _client(tp, tm or None)


def designer_info(main, tc, provider: str, model: str | None, test_provider: str | None) -> dict:
    tp = getattr(tc, "provider", None) or (test_provider or provider)
    return {"provider": tp if tc is not main else provider, "model": getattr(tc, "model", model),
            "independent": tc is not main and getattr(tc, "model", None) != getattr(main, "model", None)}


def _json_call(client, messages: list[dict], max_tokens: int) -> tuple[object, str, int]:
    """One JSON call plus at most one schema-recovery call. Returns (parsed, raw, calls_used)."""
    raw = client.chat(messages, temperature=0.0, max_tokens=max_tokens)
    parsed = prompts.parse_json(raw)
    if parsed is not None:
        return parsed, raw, 1
    raw2 = client.chat(prompts.schema_recovery_messages(messages, raw, "not a parseable JSON object"),
                       temperature=0.0, max_tokens=max_tokens)
    return prompts.parse_json(raw2), raw2, 2


# ---------------------------------------------------------------- phase 1: contract

def analyze(requirement: str, provider: str, model: str | None = None, function_name: str | None = None,
            examples: list | None = None, answers: list[dict] | None = None, auto_resolve: bool = False,
            client=None) -> dict:
    requirement = (requirement or "").strip()
    if not requirement:
        raise PipelineError("Requirement is empty")
    if len(requirement) > 4000:
        raise PipelineError("Requirement is too long (max 4000 characters)")
    t0 = time.time()
    c = _client(provider, model, client)
    # A name the requirement explicitly spells out is binding; the model may not rename it.
    sig = explicit_signature(requirement)
    function_name = function_name or (sig[0] if sig else None)
    msgs = prompts.analyze_messages(requirement, function_name, examples, answers, auto_resolve)
    try:
        raw, _, calls = _json_call(c, msgs, 1200)
    except LLMError as e:
        raise PipelineError(f"Model call failed: {e}") from e
    try:
        contract = normalize_contract(raw, requirement, function_name, examples or [])
        _bind_signature(contract, sig)
    except ContractError as e:
        try:
            contract = fallback_contract(requirement, function_name, sig, str(e))
        except ContractError:
            raise PipelineError(f"Model returned an unusable contract ({e}). Try rephrasing or retry.") from e
        contract["examples"] = examples or []
    if auto_resolve:  # no human available: take each question's recommended option and record it
        for q in contract["clarification_questions"]:
            pick = q["options"][q["recommended"]] if q["recommended"] is not None else "model's provisional assumption"
            contract["assumptions"].append(f"Auto-answered '{q['question']}' with: {pick}")
        contract["clarification_questions"] = []
    state = "needs_clarification" if contract["clarification_questions"] else "contract_ready"
    return {"state": state, "contract": contract, "model_calls": calls, "latency_s": round(time.time() - t0, 2),
            "provider": provider, "model": getattr(c, "model", model)}


# ---------------------------------------------------------------- phase 2: tests -> code -> verify

def _failure_report(syntax: dict, policy: dict | None, results: list[dict], cases: list[dict]) -> str:
    if not syntax["ok"]:
        return f"The code does not parse: {syntax['error']}\n  {syntax.get('text', '')}"
    lines = []
    if policy:
        lines += [f"Blocked: {b}" for b in policy["blocked"]] + [f"Issue: {i}" for i in policy["issues"]]
    by_id = {c["id"]: c for c in cases}
    for r in results:
        if r["status"] in ("fail", "error", "timeout"):
            c = by_id[r["test_id"]]
            exp = f"raise {c['expected_exception']}" if c.get("expected_exception") else f"return {c['expected']!r}"
            lines.append(f"- {r['test_id']} ({', '.join(c['requirement_ids'])}): call with args={c['args']!r} "
                         f"kwargs={c['kwargs']!r} should {exp}; got {r['actual']!r}. {r['bounded_error'] or ''}")
    return "\n".join(lines[:20]) or "Unknown failure."


def _verify(code: str, contract: dict, cases: list[dict], mode: str, disputed: frozenset = frozenset()) -> dict:
    syntax = check_syntax(code)
    policy, run = None, {"mode": mode, "results": []}
    if syntax["ok"]:
        policy = policy_check(code, contract)
        if policy["status"] == "fail":
            run = execute_cases(code, contract["function_name"], cases, mode="none")
            for r in run["results"]:
                r["bounded_error"] = "not executed: " + "; ".join(policy["blocked"])
        else:
            run = execute_cases(code, contract["function_name"], cases, mode=mode)
    results = run["results"]
    executed = syntax["ok"] and policy is not None and policy["status"] != "fail" and mode != "none" and bool(cases)
    if executed and disputed:
        for r in results:
            if r["test_id"] in disputed and r["status"] != "pass":
                r["status"] = "disputed"
                r["bounded_error"] = ("disputed: two independent implementations agree with each other and not with "
                                      "this test's expectation. Review the expected value.")
    counts = {s: sum(r["status"] == s for r in results)
              for s in ("pass", "fail", "error", "timeout", "not_executed", "disputed")}
    effective = len(cases) - counts["disputed"]
    if not syntax["ok"]:
        status = "failed"
    elif not executed:
        status = "not_executed"
    else:
        status = "passed" if effective > 0 and counts["pass"] == effective else "failed"
    return {"syntax": syntax, "policy": policy, "results": results, "counts": counts, "status": status,
            "execution_mode": run["mode"] if executed else "not_executed", "load_error": run.get("load_error")}


def _verify_repair(contract: dict, cases: list[dict], code: str, c, mode: str, max_repairs: int,
                   timings: dict, counter: dict, disputed: frozenset = frozenset()) -> Iterator[dict]:
    """Validate `code` against FROZEN `cases`; on failure, code-only repair up to `max_repairs` times.

    Yields stage events and returns the attempts list (use `attempts = yield from ...`).
    `counter["calls"]` is incremented for every model call.
    """
    frozen = stable_hash(cases)
    attempts = []
    for attempt in range(1, max_repairs + 2):
        t = time.time()
        yield {"type": "stage", "stage": "validate", "status": "running", "data": {"attempt": attempt}}
        v = _verify(code, contract, cases, mode, disputed)
        timings[f"validate_{attempt}"] = round(time.time() - t, 2)
        attempts.append({"attempt": attempt, "code": code, **v})
        yield {"type": "stage", "stage": "validate", "status": "done",
               "data": {"attempt": attempt, "state": "validated", **{k: v[k] for k in
                        ("syntax", "policy", "results", "counts", "status", "execution_mode", "load_error")},
                        "evidence": requirement_evidence(contract, cases, v["results"] if v["status"] != "not_executed" else None)}}
        repairable = v["status"] == "failed" or (v["policy"] and v["policy"]["status"] == "fail")
        if not repairable or attempt > max_repairs:
            break
        feedback = _failure_report(v["syntax"], v["policy"], v["results"], cases)
        t = time.time()
        yield {"type": "stage", "stage": "repair", "status": "running", "data": {"attempt": attempt, "feedback": feedback}}
        try:
            fixed = prompts.parse_generation(c.chat(prompts.repair_messages(contract, code, feedback), temperature=0.1))
            counter["calls"] += 1
        except LLMError as e:
            yield {"type": "stage", "stage": "repair", "status": "failed", "data": {"error": str(e)}}
            break
        if stable_hash(cases) != frozen:  # defensive: repair must never touch the frozen tests
            raise PipelineError("Frozen test set changed during repair; aborting.")
        code = fixed["code"]
        timings[f"repair_{attempt}"] = round(time.time() - t, 2)
        yield {"type": "stage", "stage": "repair", "status": "done", "data": {"attempt": attempt, **fixed}}
    return attempts


def _same_outcome(a: dict, b: dict) -> bool:
    """Both implementations raised the same exception type, or both returned equal values."""
    if a["status"] in ("timeout", "not_executed") or b["status"] in ("timeout", "not_executed"):
        return False
    if a.get("raised") or b.get("raised"):
        return a.get("raised") == b.get("raised")
    return values_equal(a["actual"], b["actual"])


def find_disputes(code_a: str, va: dict, code_b: str, vb: dict) -> frozenset:
    """Tests that two DIFFERENT, independently generated implementations both fail with the same outcome.

    Agreement between independent implementations against a model-written expectation is evidence that the
    expectation is wrong (dual execution agreement, cf. CodeT). Disputed tests stay frozen and visible; they
    only stop driving repair and candidate selection.
    """
    if va["execution_mode"] == "not_executed" or vb["execution_mode"] == "not_executed" or va.get("load_error") \
            or vb.get("load_error"):
        return frozenset()
    try:
        if ast.unparse(ast.parse(code_a)) == ast.unparse(ast.parse(code_b)):
            return frozenset()
    except SyntaxError:
        return frozenset()
    rb = {r["test_id"]: r for r in vb["results"]}
    out = {r["test_id"] for r in va["results"]
           if r["status"] != "pass" and rb.get(r["test_id"], {}).get("status") not in (None, "pass")
           and _same_outcome(r, rb[r["test_id"]])}
    if len(out) == len(va["results"]):  # everything disputed = no signal; keep all tests authoritative
        return frozenset()
    return frozenset(out)


def _behaviour(v: dict) -> tuple | None:
    """What a candidate actually did on every test input (expected values ignored); None if it didn't run."""
    if not v["syntax"]["ok"] or v["execution_mode"] == "not_executed" or v.get("load_error"):
        return None
    sig = []
    for r in v["results"]:
        if r["status"] == "timeout":
            sig.append(("timeout",))
        elif r.get("raised"):
            sig.append(("raise", r["raised"]))
        else:
            sig.append(("return", json.dumps(r["actual"], sort_keys=True)))
    return tuple(sig)


def select_by_agreement(cands: list[dict], trust_tests: bool = False) -> dict:
    """CodeT-style selection: group candidates that behave identically on the test inputs and pick a group.

    How much to trust the tests depends on who wrote them:
      trust_tests=True  (an independent model designed them): score = distinct implementations x tests passed
      trust_tests=False (the same model wrote tests and code): agreement first, then tests passed, because a
                        model's own expected values share its misunderstandings (measured on small models)
    Tests that a group of >= 2 distinct implementations agrees against are returned as disputed.
    `cands` items: {"source", "code", "v"}.
    """
    groups: dict = {}
    for i, cd in enumerate(cands):
        key = _behaviour(cd["v"])
        groups.setdefault(key if key is not None else ("__norun__", i), []).append(i)
    scored = []
    for key, idx in groups.items():
        norm = set()
        for i in idx:
            try:
                norm.add(ast.unparse(ast.parse(cands[i]["code"])))
            except SyntaxError:
                norm.add(cands[i]["code"])
        passes = 0 if key[0] == "__norun__" else cands[idx[0]]["v"]["counts"]["pass"]
        size = 0 if key[0] == "__norun__" else len(norm)
        has_direct = any(cands[i]["source"].startswith("direct") for i in idx)
        # Untrusted tests may only break ties after agreement and the plain-prompt default.
        rank = (size * (1 + passes), passes, has_direct) if trust_tests else (size, has_direct, passes)
        scored.append((rank, idx, size))
    scored.sort(key=lambda x: x[0], reverse=True)
    _, win, size = scored[0]
    chosen = next((i for i in win if cands[i]["source"] == "contract"), win[0])  # prefer the documented one
    v = cands[chosen]["v"]
    disputed = frozenset()
    if size >= 2:
        failed = {r["test_id"] for r in v["results"] if r["status"] != "pass"}
        if failed and len(failed) < len(v["results"]):
            disputed = frozenset(failed)
    group_of = {i: g for g, (_, idx, _) in enumerate(scored) for i in idx}
    return {"chosen": chosen, "disputed": disputed, "group_of": group_of, "groups": len(scored),
            "winning_group_size": size}


def _signature_text(contract: dict) -> str:
    parts = []
    for p in contract["parameters"]:
        d = p.get("description", "")
        parts.append(f"{p['name']}={d[len('default '):]}" if d.startswith("default ") else p["name"])
    return f"def {contract['function_name']}({', '.join(parts)})"


def _candidate_score(v: dict) -> tuple:
    return (v["syntax"]["ok"], bool(v["policy"]) and v["policy"]["status"] != "fail", v["counts"]["pass"])


def _unified(a: str, b: str, la: str, lb: str) -> str:
    return "".join(difflib.unified_diff(a.splitlines(True), b.splitlines(True), la, lb))


def _build_result(*, provider: str, c, model, contract: dict, cases: list[dict], rejected: list[str],
                  attempts: list[dict], gen: dict, examples: list[dict], test_set_hash: str, calls: int,
                  timings: dict, t_start: float, **extra) -> dict:
    # Report the best attempt (most frozen cases passing; later wins ties), so a bad repair cannot
    # replace better code. Every attempt stays in `attempts` for transparency.
    final = max(attempts, key=lambda a: (a["status"] == "passed", a["syntax"]["ok"], a["counts"]["pass"], a["attempt"]))
    return {
        "type": "result",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "recorded": False,
        "version": 1,
        "parent_run_id": None,
        "state": final["status"],
        "status": final["status"],
        "provider": provider,
        "model": getattr(c, "model", model),
        "prompt_version": prompts.PROMPT_VERSION,
        "contract": contract,
        "test_cases": cases,
        "rejected_cases": rejected,
        "code": final["code"],
        "original_code": attempts[0]["code"],
        "diff": _unified(attempts[0]["code"], final["code"], "original.py", "repaired.py"),
        "selected_attempt": final["attempt"],
        "explanation": gen.get("explanation", ""),
        "limitations": gen.get("limitations", []),
        "examples": [{"id": e["id"], "requirement": e["requirement"], "score": e["score"]} for e in examples],
        "validation": {k: final[k] for k in ("syntax", "policy", "results", "counts", "execution_mode", "load_error")},
        "evidence": requirement_evidence(contract, cases, final["results"] if final["status"] != "not_executed" else None),
        "repair_attempted": len(attempts) > 1,
        "tests_unchanged": stable_hash(cases) == test_set_hash,
        "attempts": [{"attempt": a["attempt"], "status": a["status"], "counts": a["counts"], "code": a["code"]}
                     for a in attempts],
        "hashes": {"code": stable_hash(final["code"]), "contract": stable_hash(contract), "test_set": test_set_hash},
        "model_calls": calls,
        "consensus": None,
        "test_designer": {"provider": provider, "model": getattr(c, "model", model), "independent": False},
        "timings": timings,
        "latency_s": round(time.time() - t_start, 2),
        **extra,
    }


def run_generation(contract: dict, provider: str, model: str | None = None, max_repairs: int = MAX_REPAIRS,
                   top_k: int = TOP_K_EXAMPLES, client=None, test_provider: str | None = None,
                   test_model: str | None = None, tests_client=None,
                   trust_own_tests: bool | None = None) -> Iterator[dict]:
    t_start = time.time()
    timings: dict[str, float] = {}
    try:
        contract = validate_contract(contract)
        c = _client(provider, model, client)
        tc = test_client(c, provider, model, test_provider, test_model, tests_client)
    except (ContractError, PipelineError) as e:
        yield {"type": "error", "message": str(e)}
        return
    designer = designer_info(c, tc, provider, model, test_provider)
    trust_own = TRUST_OWN_TESTS if trust_own_tests is None else trust_own_tests
    tests_trusted = designer["independent"] or trust_own
    if not tests_trusted:
        max_repairs = 0  # untrusted tests must not rewrite code
    designer["tests_trusted"] = tests_trusted
    counter = {"calls": 0}
    mode = execution_mode()

    # Retrieval: verified library snippets as style/idiom grounding (never the benchmark).
    t = time.time()
    yield {"type": "stage", "stage": "retrieve", "status": "running"}
    query = normalize_text(" ".join([contract["raw_requirement"], contract["function_name"].replace("_", " "),
                                     *[r["text"] for r in contract["requirements"]]]))
    examples = get_retriever().search(query, k=top_k)
    timings["retrieve"] = round(time.time() - t, 2)
    yield {"type": "stage", "stage": "retrieve", "status": "done",
           "data": {"examples": [{k: e[k] for k in ("id", "requirement", "score", "code")} for e in examples],
                    "mode": "hybrid (BM25 + embeddings)" if get_retriever().dense_enabled else "BM25"}}

    # Test design from the contract only, then freeze.
    t = time.time()
    yield {"type": "stage", "stage": "tests", "status": "running"}
    try:
        raw, _, n = _json_call(tc, prompts.test_design_messages(contract), 3000)
        counter["calls"] += n
    except LLMError as e:
        yield {"type": "error", "message": f"Test design failed ({designer['provider']}): {e}"}
        return
    cases, rejected = validate_cases(raw if raw is not None else [], contract)
    test_set_hash = stable_hash(cases)
    timings["tests"] = round(time.time() - t, 2)
    yield {"type": "stage", "stage": "tests", "status": "done" if cases else "failed",
           "data": {"state": "tests_ready", "test_cases": cases, "rejected": rejected, "test_set_hash": test_set_hash,
                    "evidence": requirement_evidence(contract, cases, None), "test_designer": designer}}

    # Generation never sees the tests.
    t = time.time()
    yield {"type": "stage", "stage": "generate", "status": "running"}
    try:
        gen = prompts.parse_generation(c.chat(prompts.generate_messages(contract, examples), temperature=0.2))
        counter["calls"] += 1
    except LLMError as e:
        yield {"type": "error", "message": f"Generation failed: {e}"}
        return
    timings["generate"] = round(time.time() - t, 2)
    yield {"type": "stage", "stage": "generate", "status": "done", "data": {"state": "generated", **gen}}

    # Consensus check: two more independent implementations from the plain requirement (they never see the
    # tests either), then selection by behavioural agreement + tests passed.
    start, disputed, consensus = gen["code"], frozenset(), None
    if CONSENSUS and cases and mode != "none":
        t = time.time()
        yield {"type": "stage", "stage": "consensus", "status": "running"}
        try:
            cands = [{"source": "contract", "code": gen["code"]}]
            for label, temp in (("direct", 0.2), ("direct-2", 0.8)):
                alt = prompts.parse_generation(c.chat(prompts.direct_messages(contract["raw_requirement"],
                                                                              _signature_text(contract)),
                                                      temperature=temp))
                counter["calls"] += 1
                cands.append({"source": label, "code": alt["code"]})
            for cd in cands:
                cd["v"] = _verify(cd["code"], contract, cases, mode)
            sel = select_by_agreement(cands, trust_tests=tests_trusted)
            disputed = sel["disputed"]
            start = cands[sel["chosen"]]["code"]
            consensus = {"candidates": [{"source": cd["source"], "counts": _verify(cd["code"], contract, cases, mode,
                                                                                   disputed)["counts"],
                                         "group": sel["group_of"][i], "code": cd["code"]}
                                        for i, cd in enumerate(cands)],
                         "selected": cands[sel["chosen"]]["source"], "groups": sel["groups"],
                         "winning_group_size": sel["winning_group_size"], "disputed": sorted(disputed),
                         "tests_trusted": tests_trusted}
        except LLMError as e:
            consensus = {"error": str(e)}
        timings["consensus"] = round(time.time() - t, 2)
        yield {"type": "stage", "stage": "consensus", "status": "done", "data": consensus}

    try:
        attempts = yield from _verify_repair(contract, cases, start, c, mode, max_repairs, timings, counter, disputed)
    except PipelineError as e:
        yield {"type": "error", "message": str(e)}
        return
    yield _build_result(provider=provider, c=c, model=model, contract=contract, cases=cases, rejected=rejected,
                        attempts=attempts, gen=gen, examples=examples, test_set_hash=test_set_hash,
                        calls=counter["calls"], timings=timings, t_start=t_start, test_designer=designer,
                        consensus=consensus)


def generate(contract: dict, **kwargs) -> dict:
    out: dict = {}
    for ev in run_generation(contract, **kwargs):
        if ev["type"] in ("result", "error"):
            out = ev
    return out


def run_full(requirement: str, provider: str, model: str | None = None, max_repairs: int = MAX_REPAIRS,
             client=None, test_provider: str | None = None, test_model: str | None = None,
             spec_by_tester: bool = False, trust_own_tests: bool | None = None, **kw) -> dict:
    """Non-interactive path (CLI/eval): ambiguities are auto-resolved into recorded assumptions.

    spec_by_tester: the independent test model also writes the contract ("architect"), and the
    main model only writes and repairs code ("coder").
    """
    c = _client(provider, model, client)
    architect = test_client(c, provider, model, test_provider, test_model) if spec_by_tester else c
    a = analyze(requirement, provider, model, auto_resolve=True, client=architect, **kw)
    res = generate(a["contract"], provider=provider, model=model, max_repairs=max_repairs, client=c,
                   test_provider=test_provider, test_model=test_model, trust_own_tests=trust_own_tests)
    if res.get("type") == "result":
        res["model_calls"] += a["model_calls"]
        res["latency_s"] = round(res["latency_s"] + a["latency_s"], 2)
    return res


def direct_baseline(requirement: str, provider: str, model: str | None = None, client=None) -> dict:
    """Baseline for evaluation: one direct prompt, no contract, tests, retrieval or repair."""
    t0 = time.time()
    c = _client(provider, model, client)
    code = prompts.parse_generation(c.chat(prompts.direct_messages(requirement), temperature=0.2))["code"]
    return {"code": code, "model_calls": 1, "latency_s": round(time.time() - t0, 2)}
