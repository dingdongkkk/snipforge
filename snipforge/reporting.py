"""Reporting: pytest translation, markdown report, ZIP export bundle, recorded runs."""
from __future__ import annotations

import io
import json
import re
import zipfile

from .config import DATA_DIR

RUNS_DIR = DATA_DIR / "runs"


def pytest_file(result: dict) -> str:
    """Translate the frozen declarative cases into a standalone pytest module."""
    fn = result["contract"]["function_name"]
    lines = ['"""Frozen test cases generated from the confirmed contract (SnipForge export)."""',
             "import math", "", "import pytest", "", f"from solution import {fn}", "", ""]
    for c in result["test_cases"]:
        call = f"{fn}({', '.join([repr(a) for a in c['args']] + [f'{k}={v!r}' for k, v in c['kwargs'].items()])})"
        doc = f"    # {', '.join(c['requirement_ids'])}: {c['description']}".rstrip(": ")
        lines.append(f"def test_{c['id'].lower()}():")
        lines.append(doc)
        if c.get("expected_exception"):
            lines += [f"    with pytest.raises({c['expected_exception']}):", f"        {call}"]
        elif c.get("property") == "idempotent":
            rest = [repr(a) for a in c["args"][1:]] + [f"{k}={v!r}" for k, v in c["kwargs"].items()]
            lines += [f"    first = {call}",
                      f"    assert _jsonable({fn}({', '.join(['first'] + rest)})) == _jsonable(first)"]
        elif c.get("property") == "deterministic":
            lines.append(f"    assert _jsonable({call}) == _jsonable({call})")
        elif "tolerance" in c:
            lines.append(f"    assert math.isclose({call}, {c['expected']!r}, abs_tol={c['tolerance']!r})")
        elif c.get("strict_type"):
            lines += [f"    result = _jsonable({call})",
                      f"    assert result == {c['expected']!r} and type(result) is {type(c['expected']).__name__}"]
        else:
            lines.append(f"    assert _jsonable({call}) == {c['expected']!r}")
        lines += ["", ""]
    lines += ["def _jsonable(v):",
              '    """Mirror the harness: tuples->lists, sets->sorted lists, dict keys->str."""',
              "    if isinstance(v, (list, tuple)):", "        return [_jsonable(x) for x in v]",
              "    if isinstance(v, (set, frozenset)):", "        return sorted(_jsonable(x) for x in v)",
              "    if isinstance(v, dict):", "        return {str(k): _jsonable(x) for k, x in v.items()}",
              "    return v", ""]
    return "\n".join(lines)


def report_md(result: dict) -> str:
    ct, v = result["contract"], result["validation"]
    counts = v["counts"]
    out = [f"# SnipForge report: `{ct['function_name']}`", "",
           f"- Generated: {result['created_at']} with {result['provider']} / {result['model']} "
           f"(prompt v{result['prompt_version']})" + (" (RECORDED RUN)" if result.get("recorded") else ""),
           f"- Final status: **{result['status']}**; execution: {v['execution_mode']}",
           f"- Syntax: {'valid' if v['syntax']['ok'] else v['syntax'].get('error')}; "
           f"policy: {v['policy']['status'] if v['policy'] else 'n/a'}",
           f"- Test cases: {counts['pass']} pass / {counts['fail']} fail / {counts['error']} error / "
           f"{counts['timeout']} timeout / {counts['not_executed']} not executed / {counts.get('disputed', 0)} disputed "
           f"(of {len(result['test_cases'])})",
           f"- Disputed tests (two independent implementations agree against the expectation; review): "
           f"{', '.join((result.get('consensus') or {}).get('disputed') or []) or 'none'}",
           f"- Repair attempted: {result['repair_attempted']}; frozen tests unchanged: {result['tests_unchanged']}",
           f"- Model calls: {result['model_calls']}; latency: {result['latency_s']}s",
           f"- Hashes: code {result['hashes']['code']}, contract {result['hashes']['contract']}, "
           f"tests {result['hashes']['test_set']}", "",
           "## Requirement evidence", "", "| Requirement | Cases | Outcome |", "|---|---|---|"]
    for e in result["evidence"]:
        out.append(f"| {e['requirement_id']}: {e['text']} | {', '.join(e['cases']) or '-'} | {e['outcome']} |")
    q = result.get("quality") or {}
    pt, pl = q.get("pytest") or {}, q.get("pylint") or {}
    out += ["", "## pytest + pylint", ""]
    if pt.get("executed"):
        out.append(f"- pytest: {pt.get('passed', 0)} passed, {pt.get('failed', 0)} failed, {pt.get('errors', 0)} errors "
                   f"of {pt.get('total', 0)} (`{pt.get('command', 'pytest')}`, {pt.get('duration_s')}s)")
    else:
        out.append(f"- pytest: not run ({pt.get('message', 'unavailable')})")
    if pl.get("score") is not None:
        out.append(f"- pylint: {pl['score']:.2f}/10, {pl.get('total_messages', 0)} message(s) (disabled: {pl.get('disabled')})")
        out += [f"  - line {m['line']}: {m['symbol']} ({m['id']}): {m['message']}" for m in pl.get("messages", [])[:15]]
    else:
        out.append(f"- pylint: not run ({pl.get('message') or pl.get('error') or 'unavailable'})")
    if result.get("version", 1) > 1:
        tc = result.get("test_changes") or {}
        out += ["", f"## Version {result['version']} (parent run `{result.get('parent_run_id')}`)", "",
                f"- Change: {result.get('change')}",
                f"- Tests kept: {', '.join(tc.get('kept', [])) or '-'}; removed: {', '.join(tc.get('removed', [])) or '-'}; "
                f"added: {', '.join(tc.get('added', [])) or '-'}"]
        if result.get("regression"):
            out.append(f"- Regression checks (kept tests): {result['regression']['pass']}/{result['regression']['total']} pass")
    ch = result.get("challenge")
    if ch:
        out += ["", "## Challenge", "",
                f"{len(ch['cases'])} contract-derived edge cases run: {ch['counts']['pass']} pass, "
                f"{len(ch['findings'])} finding(s)."]
        for f in ch["findings"]:
            c, r = f["case"], f["result"]
            exp = f"raise {c['expected_exception']}" if c.get("expected_exception") else c.get("property") or repr(c.get("expected"))
            out.append(f"- {c['id']} args={c['args']!r}: expected {exp}, got {r['actual']!r} "
                       f"({', '.join(x['id'] for x in f['requirements'])})")
    mu = result.get("mutation")
    if mu:
        sm = mu["summary"]
        out += ["", "## Mutation testing", "",
                f"Frozen tests detected {sm['detected']} of {mu['attempted']} mutants "
                f"({sm['survived']} survived, {sm['error']} error). Survivors may be test gaps or equivalent mutants."]
        out += [f"- {m['id']} {m['description']}: `{m['before']}` → `{m['after']}`: **{m['outcome']}**" for m in mu["mutants"]]
    out += ["", "## Assumptions", ""] + [f"- {a}" for a in ct["assumptions"] or ["(none)"]]
    out += ["", "## Limitations", ""] + [f"- {l}" for l in result["limitations"] or ["(none stated)"]]
    out += ["", "## Notes", "",
            "Test cases were designed by the model from the contract alone and frozen before code generation. "
            "They are evidence for these specific cases, not a proof of general correctness. Expected values "
            "should be reviewed by a person."]
    return "\n".join(out) + "\n"


def bundle(result: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("solution.py", result["code"])
        z.writestr("contract.json", json.dumps(result["contract"], indent=2))
        z.writestr("test_cases.json", json.dumps(result["test_cases"], indent=2))
        z.writestr("test_solution.py", pytest_file(result))
        z.writestr("report.md", report_md(result))
        history = lineage(result)
        if len(history) > 1:
            z.writestr("history.json", json.dumps(history, indent=2))
    return buf.getvalue()


def lineage(result: dict) -> list[dict]:
    """Version history, newest first: what changed, which tests changed, outcome and code per version."""
    chain, cur, seen = [], result, set()
    while cur is not None:
        chain.append({"version": cur.get("version", 1), "created_at": cur["created_at"], "status": cur["status"],
                      "change": cur.get("change"), "test_changes": cur.get("test_changes"),
                      "requirements": cur["contract"]["requirements"], "hashes": cur["hashes"], "code": cur["code"]})
        pid = cur.get("parent_run_id")
        if not pid or pid in seen:
            break
        seen.add(pid)
        cur = load_run(pid, replay=False)
    return chain


def save_run(result: dict) -> str:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = (f"{result['created_at'][:19].replace(':', '').replace('-', '')}-{result['contract']['function_name']}"
              f"-v{result.get('version', 1)}")
    run_id = re.sub(r"[^A-Za-z0-9_-]", "", run_id)
    (RUNS_DIR / f"{run_id}.json").write_text(json.dumps(result, indent=2))
    return run_id


def list_runs() -> list[dict]:
    if not RUNS_DIR.exists():
        return []
    out = []
    for p in sorted(RUNS_DIR.glob("*.json"), reverse=True)[:50]:
        try:
            r = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        out.append({"id": p.stem, "function": r["contract"]["function_name"], "status": r["status"],
                    "version": r.get("version", 1),
                    "created_at": r["created_at"], "model": r["model"]})
    return out


def load_run(run_id: str, replay: bool = True) -> dict | None:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id or ""):
        return None
    p = RUNS_DIR / f"{run_id}.json"
    if not p.exists():
        return None
    r = json.loads(p.read_text())
    if replay:
        r["recorded"] = True  # always labelled as a replay, never as a live run
    return r


def attach(run_id: str, key: str, value: dict) -> None:
    """Attach challenge/mutation results to a stored run (code, contract and tests are never modified)."""
    r = load_run(run_id, replay=False)
    if r is None:
        raise KeyError(run_id)
    r[key] = value
    (RUNS_DIR / f"{run_id}.json").write_text(json.dumps(r, indent=2))
