"""Static validation (syntax, policy, quality) and the trusted test-function runner used by the KB/benchmark builders."""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import TEST_TIMEOUT_S

# Modules/calls we will not execute inside the test sandbox.
RISKY_MODULES = {
    "subprocess": "spawns processes", "socket": "network access", "requests": "network access",
    "urllib": "network access", "http": "network access", "httpx": "network access",
    "ftplib": "network access", "smtplib": "network access", "ctypes": "native memory access",
    "multiprocessing": "spawns processes", "shutil": "bulk file operations",
}
RISKY_CALLS = {
    "eval": "dynamic code execution", "exec": "dynamic code execution", "__import__": "dynamic import",
    "os.system": "shell execution", "os.popen": "shell execution", "os.remove": "file deletion",
    "os.unlink": "file deletion", "os.rmdir": "directory deletion", "os.kill": "process control",
}


def check_syntax(code: str) -> dict:
    try:
        ast.parse(code)
        return {"ok": True}
    except SyntaxError as e:
        return {"ok": False, "error": f"SyntaxError line {e.lineno}: {e.msg}", "line": e.lineno,
                "text": (e.text or "").rstrip()}


def _call_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        return f"{f.value.id}.{f.attr}"
    return ""


def static_analysis(code: str) -> dict:
    """AST scan for safety risks plus lightweight quality signals."""
    tree = ast.parse(code)
    risks, imports = [], set()
    funcs = classes = documented = typed = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for n in names:
                root = n.split(".")[0]
                imports.add(root)
                if root in RISKY_MODULES:
                    risks.append(f"import {root} ({RISKY_MODULES[root]})")
        elif isinstance(node, ast.Call):
            name = _call_name(node)
            if name in RISKY_CALLS:
                risks.append(f"{name}() ({RISKY_CALLS[name]})")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_") or node.name == "__init__":
                funcs += 1
                documented += bool(ast.get_docstring(node))
                typed += bool(node.returns or any(a.annotation for a in node.args.args if a.arg != "self"))
        elif isinstance(node, ast.ClassDef):
            classes += 1
            documented += bool(ast.get_docstring(node))
    total = max(funcs + classes, 1)
    third_party = sorted(i for i in imports if i and i not in _stdlib_names())
    return {
        "risks": sorted(set(risks)),
        "imports": sorted(imports),
        "third_party": third_party,
        "functions": funcs,
        "classes": classes,
        "docstring_ratio": round(documented / total, 2),
        "type_hint_ratio": round(typed / max(funcs, 1), 2),
        "lint": _pyflakes(code),
    }


def _stdlib_names() -> set[str]:
    names = getattr(sys, "stdlib_module_names", None)  # 3.10+
    if names:
        return set(names)
    return {
        "abc", "argparse", "array", "ast", "asyncio", "base64", "bisect", "calendar", "collections",
        "contextlib", "copy", "csv", "dataclasses", "datetime", "decimal", "enum", "fractions",
        "functools", "hashlib", "heapq", "hmac", "html", "http", "io", "ipaddress", "itertools", "json",
        "logging", "math", "operator", "os", "pathlib", "pickle", "random", "re", "secrets", "shutil",
        "socket", "sqlite3", "statistics", "string", "struct", "subprocess", "sys", "tempfile",
        "textwrap", "threading", "time", "timeit", "typing", "unicodedata", "unittest", "urllib", "uuid",
        "warnings", "weakref", "xml", "zipfile", "zoneinfo", "ctypes", "multiprocessing", "ftplib",
        "smtplib", "queue", "glob", "fnmatch", "pprint", "traceback", "inspect", "types", "gzip",
    }


def _pyflakes(code: str) -> list[str]:
    try:
        from pyflakes.api import check
        from pyflakes.reporter import Reporter
    except ImportError:
        return []
    import io

    out = io.StringIO()
    check(code, "solution.py", Reporter(out, out))
    return [l for l in out.getvalue().splitlines() if l.strip()][:10]


_RUNNER = r'''
import json, sys, traceback, types, linecache
sys.path.insert(0, ".")
sys.setrecursionlimit(5000)

# Minimal pytest shim so tests using pytest.raises/approx still run without pytest installed.
try:
    import pytest  # noqa
except ImportError:
    pt = types.ModuleType("pytest")
    class _Raises:
        def __init__(self, exc, match=None): self.exc, self.match = exc, match
        def __enter__(self): return self
        def __exit__(self, et, ev, tb):
            if et is None: raise AssertionError(f"DID NOT RAISE {self.exc}")
            if not issubclass(et, self.exc): return False
            if self.match:
                import re
                assert re.search(self.match, str(ev)), f"message {ev!r} does not match {self.match!r}"
            return True
    def approx(v, rel=1e-6, abs_tol=1e-12):
        class A:
            def __eq__(s, o): return abs(o - v) <= max(rel * abs(v), abs_tol)
            def __repr__(s): return f"approx({v})"
        return A()
    pt.raises, pt.approx = _Raises, approx
    sys.modules["pytest"] = pt

def emit(obj):
    print("__SNIPFORGE__" + json.dumps(obj))

ns = {"__name__": "solution"}
try:
    src = open("solution.py").read()
    exec(compile(src, "solution.py", "exec"), ns)
except BaseException as e:
    emit({"load_error": "".join(traceback.format_exception_only(type(e), e)).strip(),
          "trace": traceback.format_exc(limit=4)})
    sys.exit(0)

mod = types.ModuleType("solution"); mod.__dict__.update(ns); sys.modules["solution"] = mod
tns = dict(ns); tns["__name__"] = "tests"
try:
    exec(compile(open("tests.py").read(), "tests.py", "exec"), tns)
except BaseException as e:
    emit({"load_error": "tests.py: " + "".join(traceback.format_exception_only(type(e), e)).strip(),
          "trace": traceback.format_exc(limit=4)})
    sys.exit(0)

results = []
for name, fn in list(tns.items()):
    if not (name.startswith("test_") and callable(fn)):
        continue
    try:
        fn()
        results.append({"name": name, "passed": True})
    except BaseException as e:
        tb = traceback.extract_tb(e.__traceback__)
        frame = tb[-1] if tb else None
        line = linecache.getline(frame.filename, frame.lineno).strip() if frame else ""
        msg = "".join(traceback.format_exception_only(type(e), e)).strip()
        results.append({"name": name, "passed": False, "error": msg,
                        "where": f"{frame.filename}:{frame.lineno}" if frame else "", "line": line})
emit({"results": results})
'''


def _limits():  # pragma: no cover - runs in child process
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (int(TEST_TIMEOUT_S), int(TEST_TIMEOUT_S) + 1))
        if sys.platform != "darwin":
            resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))
    except Exception:
        pass


def run_tests(code: str, tests: str, timeout: float = TEST_TIMEOUT_S) -> dict:
    """Execute solution + tests in an isolated subprocess inside a throwaway directory."""
    with tempfile.TemporaryDirectory(prefix="snipforge_") as tmp:
        Path(tmp, "solution.py").write_text(code)
        Path(tmp, "tests.py").write_text(tests or "")
        Path(tmp, "_runner.py").write_text(_RUNNER)
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "_runner.py"], cwd=tmp, env=env, capture_output=True, text=True,
                timeout=timeout, preexec_fn=_limits if os.name == "posix" else None,
            )
        except subprocess.TimeoutExpired:
            return {"ran": True, "timeout": True, "passed": 0, "total": 0, "results": [],
                    "error": f"Timed out after {timeout:.0f}s (infinite loop or very slow code?)"}
    payload = None
    for line in proc.stdout.splitlines():
        if line.startswith("__SNIPFORGE__"):
            payload = json.loads(line[len("__SNIPFORGE__"):])
    if payload is None:
        return {"ran": True, "passed": 0, "total": 0, "results": [],
                "error": (proc.stderr or "Runner produced no output").strip()[-800:]}
    if "load_error" in payload:
        return {"ran": True, "passed": 0, "total": 0, "results": [], "error": payload["load_error"],
                "trace": payload.get("trace", "")}
    res = payload["results"]
    return {"ran": True, "passed": sum(r["passed"] for r in res), "total": len(res), "results": res,
            "stdout": "\n".join(l for l in proc.stdout.splitlines() if not l.startswith("__SNIPFORGE__"))[-500:]}



def policy_check(code: str, contract: dict) -> dict:
    """Static gate before execution: entry point, signature, dependencies, disallowed operations.

    This is an early filter, not a security boundary; isolation comes from runner.py.
    """
    issues, blocked = [], []
    tree = ast.parse(code)
    name = contract["function_name"]
    fn = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name), None)
    if fn is None:
        blocked.append(f"entry point `{name}` is not defined at module level")
    else:
        got = [a.arg for a in fn.args.posonlyargs + fn.args.args]
        want = [p["name"] for p in contract.get("parameters", [])]
        if want and got[: len(want)] != want:
            issues.append(f"signature is ({', '.join(got)}) but the contract expects ({', '.join(want)})")
    st = static_analysis(code)
    blocked += [f"disallowed: {r}" for r in st["risks"]]
    blocked += [f"non-stdlib dependency: {m}" for m in st["third_party"]]
    return {"status": "fail" if blocked else ("warn" if issues else "pass"),
            "blocked": blocked, "issues": issues, "static": st}
