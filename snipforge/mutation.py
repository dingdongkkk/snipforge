"""Test the tests: deterministic AST mutation testing against the frozen test set.

At most MAX_MUTANTS small, deterministic mutations (no model calls) are applied to passing code.
Each mutant runs against the same frozen cases in the isolated runner:
  detected - at least one case failed/errored/timed out (the tests noticed the change)
  survived - every case still passed (possible coverage gap, or an equivalent mutation)
  error    - the mutant could not be loaded or run at all
A survivor is not proof of a defect: some mutations do not change behaviour.
"""
from __future__ import annotations

import ast
import copy
import difflib

from .runner import execute_cases, execution_mode

MAX_MUTANTS = 5

_CMP_SWAP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq,
             ast.NotEq: ast.Eq, ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Is: ast.IsNot, ast.IsNot: ast.Is}
_BIN_SWAP = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.FloorDiv, ast.Div: ast.Mult,
             ast.FloorDiv: ast.Mult, ast.Mod: ast.FloorDiv}
_SYM = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Eq: "==", ast.NotEq: "!=", ast.In: "in",
        ast.NotIn: "not in", ast.Is: "is", ast.IsNot: "is not", ast.Add: "+", ast.Sub: "-", ast.Mult: "*",
        ast.Div: "/", ast.FloorDiv: "//", ast.Mod: "%", ast.And: "and", ast.Or: "or"}
# Category priority: boundaries first (most informative for business rules).
_PRIORITY = ["boundary", "constant", "logic", "arithmetic", "negation"]


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def _sites(tree: ast.AST) -> list[tuple[int, str, str]]:
    """(walk index, category, description) for every mutable site, in deterministic walk order."""
    skip = _docstring_nodes(tree)
    out = []
    for i, node in enumerate(ast.walk(tree)):
        if isinstance(node, ast.Compare) and type(node.ops[0]) in _CMP_SWAP:
            op = type(node.ops[0])
            comp0 = node.comparators[0]
            # Comparisons against a real threshold (not 0/None/True) are the most informative boundaries.
            threshold = isinstance(comp0, ast.Constant) and comp0.value not in (0, None, True, False, "")
            out.append((i if threshold else 10_000 + i, "boundary", f"`{_SYM[op]}` → `{_SYM[_CMP_SWAP[op]]}`"))
            for comp in node.comparators[:1]:
                if isinstance(comp, ast.Constant) and type(comp.value) is int and comp.value != 0:
                    out.append((i, "constant", f"limit {comp.value} → {comp.value + 1}"))
        elif isinstance(node, ast.BoolOp):
            op = type(node.op)
            out.append((i, "logic", f"`{_SYM[op]}` → `{'or' if op is ast.And else 'and'}`"))
        elif isinstance(node, ast.BinOp) and type(node.op) in _BIN_SWAP and id(node) not in skip:
            op = type(node.op)
            out.append((i, "arithmetic", f"`{_SYM[op]}` → `{_SYM[_BIN_SWAP[op]]}`"))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            out.append((i, "negation", "remove `not`"))
    return out


def _apply(tree: ast.AST, index: int, category: str) -> ast.AST:
    tree = copy.deepcopy(tree)
    node = list(ast.walk(tree))[index]
    if category == "boundary":
        node.ops[0] = _CMP_SWAP[type(node.ops[0])]()
    elif category == "constant":
        node.comparators[0] = ast.Constant(node.comparators[0].value + 1)
    elif category == "logic":
        node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
    elif category == "arithmetic":
        node.op = _BIN_SWAP[type(node.op)]()
    elif category == "negation":  # `not x` -> `bool(x)`
        target = node

        class _DropNot(ast.NodeTransformer):
            def visit_UnaryOp(self, n):
                self.generic_visit(n)
                return ast.Call(ast.Name("bool", ast.Load()), [n.operand], []) if n is target else n

        tree = _DropNot().visit(tree)
    return ast.fix_missing_locations(tree)


_QUOTA = [("boundary", 2), ("constant", 1), ("logic", 1), ("arithmetic", 1), ("negation", 1)]


def _select(sites: list[tuple[int, str, str]], limit: int) -> list[tuple[int, str, str]]:
    """Quota per category (thresholds first), then fill any remaining slots in priority order."""
    buckets = {c: sorted(s for s in sites if s[1] == c) for c in _PRIORITY}
    chosen = []
    for cat, n in _QUOTA:
        while n and buckets[cat] and len(chosen) < limit:
            chosen.append(buckets[cat].pop(0)); n -= 1
    for cat in _PRIORITY:
        while buckets[cat] and len(chosen) < limit:
            chosen.append(buckets[cat].pop(0))
    return [(i % 10_000, c, d) for i, c, d in chosen]


def generate_mutants(code: str, limit: int = MAX_MUTANTS) -> list[dict]:
    tree = ast.parse(code)
    base = ast.unparse(tree)
    mutants = []
    for n, (index, category, desc) in enumerate(_select(_sites(tree), limit), 1):
        try:
            mutated = ast.unparse(_apply(tree, index, category))
        except Exception:
            continue
        if mutated == base:
            continue
        changed = [l[1:] for l in difflib.unified_diff(base.splitlines(), mutated.splitlines(), lineterm="", n=0)
                   if l.startswith(("-", "+")) and not l.startswith(("---", "+++"))]
        mutants.append({"id": f"M{n}", "category": category, "description": desc, "code": mutated,
                        "before": changed[0].strip() if changed else "", "after": changed[-1].strip() if changed else ""})
    return mutants


def mutation_test(run: dict) -> dict:
    """Run up to MAX_MUTANTS mutants of a PASSING run's code against its frozen tests."""
    if run["status"] != "passed":
        raise ValueError("Mutation testing only runs on code that passes its frozen tests.")
    fn, cases, mode = run["contract"]["function_name"], run["test_cases"], execution_mode()
    out = []
    for m in generate_mutants(run["code"]):
        res = execute_cases(m["code"], fn, cases, mode=mode)
        statuses = [r["status"] for r in res["results"]]
        if res.get("load_error"):
            outcome, killed_by = "error", []
        elif any(s in ("fail", "error", "timeout") for s in statuses):
            outcome = "detected"
            killed_by = [r["test_id"] for r in res["results"] if r["status"] in ("fail", "error", "timeout")]
        elif all(s == "pass" for s in statuses):
            outcome, killed_by = "survived", []
        else:
            outcome, killed_by = "error", []
        out.append({k: m[k] for k in ("id", "category", "description", "before", "after")} |
                   {"outcome": outcome, "detected_by": killed_by, "error": res.get("load_error")})
    summary = {o: sum(m["outcome"] == o for m in out) for o in ("detected", "survived", "error")}
    return {"mutants": out, "summary": summary, "attempted": len(out), "execution_mode": mode,
            "test_set_hash": run["hashes"]["test_set"], "model_calls": 0}
