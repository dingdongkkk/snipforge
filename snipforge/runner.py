"""Execution boundary: runs declarative test cases through the trusted harness and compares results.

Modes (SNIPFORGE_RUNNER):
  auto    - docker if the runner image is built, otherwise process (default)
  docker  - ephemeral container: no network, read-only FS, no capabilities, CPU/memory/PID limits
  process - separate `python -I` process in a temp dir with a stripped env and CPU/time limits
  none    - never execute; every case reports `not_executed`
Generated code never runs in the server process. Any crash, timeout or
malformed output fails closed: a case passes only when the parent saw a matching result.
"""
from __future__ import annotations

import json
import math
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

from .config import TEST_TIMEOUT_S

HARNESS = Path(__file__).with_name("harness.py")
DOCKER_IMAGE = os.getenv("SNIPFORGE_RUNNER_IMAGE", "snipforge-runner:1")
RUNNER_MODE = os.getenv("SNIPFORGE_RUNNER", "auto")
MAX_OUTPUT = 1_000_000


@lru_cache(maxsize=1)
def _docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "image", "inspect", DOCKER_IMAGE], capture_output=True,
                              timeout=10).returncode == 0
    except Exception:
        return False


def execution_mode() -> str:
    if RUNNER_MODE in ("none", "process"):
        return RUNNER_MODE
    if RUNNER_MODE == "docker":
        return "docker" if _docker_ready() else "none"  # requested docker but unavailable: fail closed
    return "docker" if _docker_ready() else "process"


def _limits():  # pragma: no cover - runs in the child
    try:
        import resource

        cpu = int(TEST_TIMEOUT_S) + 1
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
        if sys.platform != "darwin":
            resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))
    except Exception:
        pass


def _run_child(job: dict, mode: str, timeout: float) -> tuple[str, str]:
    payload = json.dumps(job)
    if mode == "docker":
        name = f"snipforge-{secrets.token_hex(6)}"
        cmd = ["docker", "run", "--rm", "-i", "--name", name, "--network", "none", "--read-only",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "65534:65534",
               "--memory", "256m", "--cpus", "1", "--pids-limit", "64",
               "--tmpfs", "/tmp:rw,size=16m,noexec", "-w", "/tmp", DOCKER_IMAGE,
               "python", "-I", "/harness/harness.py"]
        try:
            p = subprocess.run(cmd, input=payload, capture_output=True, text=True, timeout=timeout + 5)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
            raise
        return p.stdout[:MAX_OUTPUT], p.stderr[-2000:]
    with tempfile.TemporaryDirectory(prefix="snipforge_") as tmp:
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
        p = subprocess.run([sys.executable, "-I", str(HARNESS)], input=payload, cwd=tmp, env=env,
                           capture_output=True, text=True, timeout=timeout,
                           preexec_fn=_limits if os.name == "posix" else None)
        return p.stdout[:MAX_OUTPUT], p.stderr[-2000:]


def values_equal(expected, actual, tol: float | None = None, strict: bool = False) -> bool:
    """Exact JSON-level comparison; booleans never equal numbers; tolerance only if the case sets one;
    `strict` additionally distinguishes int from float (e.g. "return an integer")."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        return type(expected) is type(actual) and expected == actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if strict and type(expected) is not type(actual):
            return False
        if tol is not None:
            return math.isclose(expected, actual, abs_tol=tol, rel_tol=0)
        return expected == actual
    if isinstance(expected, list) and isinstance(actual, list):
        return len(expected) == len(actual) and all(values_equal(e, a, tol, strict) for e, a in zip(expected, actual))
    if isinstance(expected, dict) and isinstance(actual, dict):
        return expected.keys() == actual.keys() and all(values_equal(expected[k], actual[k], tol, strict) for k in expected)
    if expected is None or actual is None:
        return expected is actual
    return type(expected) is type(actual) and expected == actual


def _judge(case: dict, out: dict | None) -> dict:
    base = {"test_id": case["id"], "expected": case.get("expected"), "property": case.get("property"),
            "expected_exception": case.get("expected_exception"), "actual": None,
            "duration_ms": None, "bounded_error": None}
    if out is None:
        return {**base, "status": "error", "bounded_error": "no result reported for this case"}
    base["duration_ms"] = out.get("duration_ms")
    if out["kind"] == "raise":
        base["actual"] = f"raised {out['exc_type']}: {out['message']}"
        base["raised"] = out["exc_type"]
        if case.get("expected_exception"):
            ok = case["expected_exception"] in out.get("mro", [])
            return {**base, "status": "pass" if ok else "fail",
                    "bounded_error": None if ok else f"expected {case['expected_exception']}, got {out['exc_type']}"}
        return {**base, "status": "error", "bounded_error": f"{out['exc_type']}: {out['message']}"}
    if out["kind"] == "property":
        first, again = out["values"]
        base["actual"] = first
        ok = values_equal(first, again)
        return {**base, "status": "pass" if ok else "fail",
                "bounded_error": None if ok else f"{case['property']} property violated: second result {again!r}"[:400]}
    base["actual"] = out["value"]
    if case.get("expected_exception"):
        return {**base, "status": "fail", "bounded_error": f"expected {case['expected_exception']} to be raised"}
    ok = values_equal(case["expected"], out["value"], case.get("tolerance"), case.get("strict_type", False))
    why = "returned value differs from expected"
    if not ok and case.get("strict_type") and values_equal(case["expected"], out["value"], case.get("tolerance")):
        why = f"value matches but type differs (expected {type(case['expected']).__name__})"
    return {**base, "status": "pass" if ok else "fail", "bounded_error": None if ok else why}


def execute_cases(code: str, entry_point: str, cases: list[dict], timeout: float = TEST_TIMEOUT_S,
                  mode: str | None = None) -> dict:
    """Run frozen cases against `code`. Returns {mode, results[], load_error?}."""
    mode = mode or execution_mode()
    if mode == "none" or not cases:
        return {"mode": mode, "results": [{"test_id": c["id"], "status": "not_executed", "expected": c.get("expected"),
                                           "expected_exception": c.get("expected_exception"), "actual": None,
                                           "duration_ms": None, "bounded_error": "execution unavailable"}
                                          for c in cases]}
    nonce = "@@" + secrets.token_hex(16) + "@@"
    job = {"nonce": nonce, "code": code, "entry_point": entry_point,
           "cases": [{"id": c["id"], "args": c["args"], "kwargs": c["kwargs"], "property": c.get("property")}
                     for c in cases]}
    try:
        stdout, stderr = _run_child(job, mode, timeout)
    except subprocess.TimeoutExpired:
        return {"mode": mode, "timeout": True,
                "results": [{"test_id": c["id"], "status": "timeout", "expected": c.get("expected"),
                             "expected_exception": c.get("expected_exception"), "actual": None, "duration_ms": None,
                             "bounded_error": f"timed out after {timeout:.0f}s"} for c in cases]}
    outs, load_error, done = {}, None, False
    for line in stdout.splitlines():
        if not line.startswith(nonce):
            continue
        try:
            rec = json.loads(line[len(nonce):])
        except json.JSONDecodeError:
            continue
        if "load_error" in rec:
            load_error = rec["load_error"]
        elif rec.get("done"):
            done = True
        elif rec.get("id"):
            outs[rec["id"]] = rec
    if load_error or not done:
        err = load_error or ("runner crashed: " + (stderr.strip().splitlines() or ["no output"])[-1])[:400]
        return {"mode": mode, "load_error": err,
                "results": [{**_judge(c, outs.get(c["id"])), **({} if c["id"] in outs else {"bounded_error": err})}
                            for c in cases]}
    return {"mode": mode, "results": [_judge(c, outs.get(c["id"])) for c in cases]}
