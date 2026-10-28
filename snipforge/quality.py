"""Industry-standard checks on top of our own harness: real pytest runs and pylint scoring.

Both run as separate processes in a throwaway temp directory with a stripped environment and limits
(the same boundary as runner.py's process mode). They are optional: if pytest/pylint are not installed,
the report says so instead of pretending. Install with `pip install -r requirements.txt`.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from .runner import _limits, execution_mode

# Rules that don't make sense for a single generated snippet.
PYLINT_DISABLE = "C0114,C0115"  # missing module/class docstring


def available(tool: str) -> bool:
    return importlib.util.find_spec(tool) is not None


def tools() -> dict:
    return {"pytest": available("pytest"), "pylint": available("pylint")}


def _env() -> dict:
    return {"PATH": os.environ.get("PATH", ""), "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}


def run_pytest(code: str, test_source: str, timeout: float = 30) -> dict:
    """Run `test_solution.py` (frozen tests translated to pytest) against `solution.py` with real pytest."""
    if not available("pytest"):
        return {"available": False, "message": "pytest is not installed (pip install -r requirements.txt)"}
    if execution_mode() == "none":
        return {"available": True, "executed": False, "message": "execution is disabled"}
    with tempfile.TemporaryDirectory(prefix="snipforge_pytest_") as tmp:
        Path(tmp, "solution.py").write_text(code)
        Path(tmp, "test_solution.py").write_text(test_source)
        cmd = [sys.executable, "-I", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--junitxml=report.xml",
               "--rootdir", tmp, "test_solution.py"]
        try:
            p = subprocess.run(cmd, cwd=tmp, env=_env(), capture_output=True, text=True, timeout=timeout,
                               preexec_fn=_limits if os.name == "posix" else None)
        except subprocess.TimeoutExpired:
            return {"available": True, "executed": True, "timeout": True, "passed": 0, "failed": 0, "errors": 1,
                    "total": 0, "cases": [], "output": f"pytest timed out after {timeout:.0f}s"}
        report = Path(tmp, "report.xml")
        cases, totals = [], {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
        duration = None
        if report.exists():
            root = ET.parse(report).getroot()
            suite = root if root.tag == "testsuite" else root.find("testsuite")
            duration = float(suite.get("time", 0)) if suite is not None else None
            for tc in root.iter("testcase"):
                status, message = "passed", ""
                for tag in ("failure", "error", "skipped"):
                    el = tc.find(tag)
                    if el is not None:
                        status = {"failure": "failed", "error": "errors", "skipped": "skipped"}[tag]
                        message = (el.get("message") or el.text or "").strip()[:300]
                        break
                totals[status] += 1
                cases.append({"name": tc.get("name"), "status": status.rstrip("s") if status == "errors" else status,
                              "message": message})
    return {"available": True, "executed": True, "exit_code": p.returncode, **totals, "total": len(cases),
            "duration_s": duration, "cases": cases, "command": "pytest -q test_solution.py",
            "output": (p.stdout + p.stderr)[-3000:]}


def run_pylint(code: str, timeout: float = 45) -> dict:
    """Static analysis with pylint (code is analysed, not executed). Returns score /10 and messages."""
    if not available("pylint"):
        return {"available": False, "message": "pylint is not installed (pip install -r requirements.txt)"}
    with tempfile.TemporaryDirectory(prefix="snipforge_pylint_") as tmp:
        Path(tmp, "solution.py").write_text(code)
        cmd = [sys.executable, "-I", "-m", "pylint", "solution.py", "--output-format=json2", "--persistent=n",
               "--score=y", f"--disable={PYLINT_DISABLE}", "--max-line-length=110"]
        try:
            p = subprocess.run(cmd, cwd=tmp, env=_env(), capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"available": True, "error": f"pylint timed out after {timeout:.0f}s"}
    try:
        data = json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"available": True, "error": (p.stderr or p.stdout or "pylint produced no output")[-400:]}
    msgs = [{"type": m.get("type"), "id": m.get("messageId"), "symbol": m.get("symbol"), "line": m.get("line"),
             "message": m.get("message")} for m in data.get("messages", [])]
    stats = data.get("statistics", {})
    return {"available": True, "score": stats.get("score"), "counts": stats.get("messageTypeCount", {}),
            "messages": msgs[:40], "total_messages": len(msgs), "disabled": PYLINT_DISABLE}


def quality_report(code: str, test_source: str | None) -> dict:
    """pytest (if there are tests) + pylint for a final snippet."""
    return {"pytest": run_pytest(code, test_source) if test_source else
            {"available": available("pytest"), "executed": False, "message": "no frozen tests"},
            "pylint": run_pylint(code), "tools": tools()}
