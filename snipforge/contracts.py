"""Data contracts: requirement contract, declarative test cases, hashes.

Plain dicts + explicit validation keep the core dependency-free while still
rejecting malformed model output before anything runs.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid

SCHEMA_VERSION = "1.0"
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REQ_ID = re.compile(r"^R[1-9][0-9]*$")
PROPERTIES = {
    "idempotent": "calling the function again on its own result returns the same result",
    "deterministic": "two calls with identical inputs return identical results",
}
_EXC = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(Error|Exception|Exit|Interrupt)$")
MAX_CASE_JSON = 20_000


class ContractError(ValueError):
    pass


def stable_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def _str_list(v) -> list[str]:
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v if str(x).strip()]


MAX_OPTIONS = 4


def normalize_questions(raw) -> list[dict]:
    """Clarification questions as multiple choice: {id, question, options[], recommended, why}.

    Plain strings (older/smaller models) become open questions with no options; the UI always offers
    an "Other" free-text answer as well. `recommended` is an index into options, or None.
    """
    out = []
    for q in raw if isinstance(raw, list) else []:
        if isinstance(q, str):
            text, opts, rec, why = q, [], None, ""
        elif isinstance(q, dict):
            text = q.get("question") or q.get("text") or ""
            opts = []
            for o in q.get("options") or []:
                o = (o.get("label") or o.get("text") or "") if isinstance(o, dict) else o
                o = str(o).strip()
                if o and o not in opts:
                    opts.append(o)
            opts = opts[:MAX_OPTIONS]
            rec, why = q.get("recommended"), str(q.get("why") or "").strip()
        else:
            continue
        if not str(text).strip():
            continue
        if isinstance(rec, str):
            rec = opts.index(rec) if rec in opts else (int(rec) if rec.isdigit() else None)
        if not (isinstance(rec, int) and not isinstance(rec, bool) and 0 <= rec < len(opts)):
            rec = None
        out.append({"id": f"Q{len(out) + 1}", "question": str(text).strip(), "options": opts,
                    "recommended": rec, "why": why})
    return out[:5]


def normalize_contract(raw: dict, requirement: str, function_name: str | None = None,
                       examples: list | None = None, request_id: str | None = None) -> dict:
    """Coerce model output into a RequirementContract; raise ContractError if unusable."""
    if not isinstance(raw, dict):
        raise ContractError("contract is not a JSON object")
    name = (function_name or raw.get("function_name") or "").strip()
    if not _IDENT.match(name):
        raise ContractError(f"invalid function_name: {name!r}")
    params = []
    for p in raw.get("parameters") or []:
        if isinstance(p, str):
            p = {"name": p.split(":")[0].strip(), "type": p.split(":")[1].strip() if ":" in p else "Any"}
        if isinstance(p, dict) and _IDENT.match(str(p.get("name", ""))):
            params.append({"name": p["name"], "type": str(p.get("type") or "Any"),
                           "description": str(p.get("description") or "")})
    reqs = []
    for r in raw.get("requirements") or []:
        text = r.get("text") if isinstance(r, dict) else r
        if text and str(text).strip():
            reqs.append({"id": r.get("id") if isinstance(r, dict) else None, "text": str(text).strip()})
    if not reqs:
        raise ContractError("contract has no requirements")
    ids = [r["id"] for r in reqs]
    if not all(isinstance(i, str) and _REQ_ID.match(i) for i in ids) or len(set(ids)) != len(ids):
        # Fresh model output: number R1..Rn. Already-valid unique ids are kept so revisions stay traceable.
        reqs = [{"id": f"R{n}", "text": r["text"]} for n, r in enumerate(reqs, 1)]
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id or uuid.uuid4().hex[:12],
        "raw_requirement": requirement,
        "function_name": name,
        "parameters": params,
        "return_type": str(raw.get("return_type") or "Any"),
        "requirements": reqs,
        "assumptions": _str_list(raw.get("assumptions")),
        "edge_cases": _str_list(raw.get("edge_cases")),
        "clarification_questions": normalize_questions(raw.get("clarification_questions")),
        "examples": examples if examples is not None else (raw.get("examples") or []),
    }


def validate_contract(contract: dict) -> dict:
    """Re-validate a contract coming back from the UI (the user may have edited it)."""
    return normalize_contract(contract, contract.get("raw_requirement", ""), contract.get("function_name"),
                              contract.get("examples") or [], contract.get("request_id"))


def validate_cases(raw_cases, contract: dict, prefix: str = "T", start: int = 1,
                   allowed_ids: set[str] | None = None) -> tuple[list[dict], list[str]]:
    """Return (valid_cases, rejection_reasons).

    Each case has exactly one expectation: `expected`, `expected_exception`, or an approved `property`.
    `allowed_ids` restricts which requirements new cases may target (used for revisions).
    """
    if isinstance(raw_cases, dict):
        raw_cases = raw_cases.get("test_cases") or raw_cases.get("cases") or []
    if not isinstance(raw_cases, list):
        return [], ["test cases are not a list"]
    req_ids = {r["id"] for r in contract["requirements"]}
    cases, errors = [], []
    seen_inputs = set()
    for i, c in enumerate(raw_cases, 1):
        if not isinstance(c, dict):
            errors.append(f"case {i}: not an object")
            continue
        has_exp, has_exc, prop = "expected" in c, bool(c.get("expected_exception")), c.get("property")
        if prop is not None and prop not in PROPERTIES:
            errors.append(f"case {i}: unsupported property {prop!r}")
            continue
        if has_exp + has_exc + (prop is not None) != 1:
            errors.append(f"case {i}: needs exactly one of expected / expected_exception / property")
            continue
        args = c.get("args", [])
        kwargs = c.get("kwargs", {}) or {}
        if not isinstance(args, list) or not isinstance(kwargs, dict):
            errors.append(f"case {i}: args must be a list and kwargs an object")
            continue
        rids = [r for r in (c.get("requirement_ids") or []) if r in req_ids]
        if not rids:
            errors.append(f"case {i}: no valid requirement_ids")
            continue
        if allowed_ids is not None and not set(rids) & allowed_ids:
            errors.append(f"case {i}: does not target a changed requirement")
            continue
        case = {"id": f"{prefix}{start + len(cases)}", "requirement_ids": rids, "description": str(c.get("description") or ""),
                "args": args, "kwargs": kwargs}
        if has_exc:
            exc = str(c["expected_exception"]).split(".")[-1].strip()
            if not _EXC.match(exc):
                errors.append(f"case {i}: invalid exception name {exc!r}")
                continue
            case["expected_exception"] = exc
        elif prop is not None:
            case["property"] = prop
        else:
            case["expected"] = c["expected"]
        if isinstance(c.get("tolerance"), (int, float)) and not isinstance(c.get("tolerance"), bool):
            case["tolerance"] = float(c["tolerance"])
        if c.get("strict_type") is True and "expected" in case:
            case["strict_type"] = True
        if len(json.dumps(case)) > MAX_CASE_JSON:
            errors.append(f"case {i}: too large")
            continue
        if input_key(case) in seen_inputs:
            errors.append(f"case {i}: duplicate input")
            continue
        seen_inputs.add(input_key(case))
        case["id"] = f"{prefix}{start + len(cases)}"
        cases.append(case)
    return cases, errors


def input_key(case: dict) -> str:
    return json.dumps([case["args"], case["kwargs"], case.get("property")], sort_keys=True)


def next_case_number(cases: list[dict], prefix: str = "T") -> int:
    nums = [int(c["id"][len(prefix):]) for c in cases if c["id"].startswith(prefix) and c["id"][len(prefix):].isdigit()]
    return max(nums, default=0) + 1


def requirement_evidence(contract: dict, cases: list[dict], results: list[dict] | None) -> list[dict]:
    """Requirement -> linked cases -> outcome. Untested requirements say so explicitly."""
    by_id = {r["test_id"]: r for r in (results or [])}
    rows = []
    for req in contract["requirements"]:
        linked = [c["id"] for c in cases if req["id"] in c["requirement_ids"]]
        if not linked:
            outcome = "not tested"
        elif not results:
            outcome = "not executed"
        else:
            statuses = [by_id.get(t, {}).get("status", "not_executed") for t in linked]
            if all(s == "pass" for s in statuses):
                outcome = "passed"
            elif any(s in ("fail", "error", "timeout") for s in statuses):
                outcome = "failed"
            elif "disputed" in statuses and all(s in ("pass", "disputed") for s in statuses):
                outcome = "disputed"
            else:
                outcome = "not executed"
        rows.append({"requirement_id": req["id"], "text": req["text"], "cases": linked, "outcome": outcome})
    return rows
