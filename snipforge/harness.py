"""Trusted execution harness. Runs in an isolated child process or container.

It reads one job from stdin: {"nonce", "code", "entry_point", "cases": [{"id", "args", "kwargs", "property"?}]}.
Expected values are never sent here; this process only reports what the code
returned or raised, and the parent process decides pass/fail. Generated code
cannot report its own status.
Standard library only, so it also runs unchanged inside the runner container.
"""
import contextlib
import copy
import io
import json
import sys
import time
import traceback

MAX_TEXT = 400


def to_jsonable(v, depth=0):
    if depth > 50:
        return {"__repr__": "<too deep>"}
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (list, tuple)):
        return [to_jsonable(x, depth + 1) for x in v]
    if isinstance(v, (set, frozenset)):
        items = [to_jsonable(x, depth + 1) for x in v]
        try:
            return sorted(items)
        except TypeError:
            return items
    if isinstance(v, dict):
        # JSON object keys are strings, so expectations written in JSON compare against str keys.
        return {str(k): to_jsonable(x, depth + 1) for k, x in v.items()}
    return {"__repr__": repr(v)[:MAX_TEXT]}


def main():
    job = json.loads(sys.stdin.read())
    nonce = job["nonce"]
    real_out = sys.stdout

    def emit(obj):
        real_out.write(nonce + json.dumps(obj) + "\n")
        real_out.flush()

    ns = {"__name__": "solution"}
    load_out = io.StringIO()
    try:
        with contextlib.redirect_stdout(load_out):
            exec(compile(job["code"], "solution.py", "exec"), ns)
    except BaseException as e:  # noqa: BLE001 - report every failure mode
        emit({"load_error": "".join(traceback.format_exception_only(type(e), e)).strip()[:MAX_TEXT]})
        return
    fn = ns.get(job["entry_point"])
    if not callable(fn):
        emit({"load_error": f"entry point {job['entry_point']!r} is not defined or not callable"})
        return
    for case in job["cases"]:
        args, kwargs = copy.deepcopy(case.get("args", [])), copy.deepcopy(case.get("kwargs", {}))
        buf = io.StringIO()
        t0 = time.perf_counter()
        prop = case.get("property")
        try:
            with contextlib.redirect_stdout(buf):
                value = fn(*args, **kwargs)
                if prop == "idempotent":  # f(f(x), *rest) vs f(x)
                    again = fn(copy.deepcopy(value), *copy.deepcopy(case.get("args", [])[1:]),
                               **copy.deepcopy(case.get("kwargs", {})))
                elif prop == "deterministic":
                    again = fn(*copy.deepcopy(case.get("args", [])), **copy.deepcopy(case.get("kwargs", {})))
            if prop:
                res = {"kind": "property", "values": [to_jsonable(value), to_jsonable(again)]}
            else:
                res = {"kind": "return", "value": to_jsonable(value)}
        except BaseException as e:  # noqa: BLE001
            res = {"kind": "raise", "exc_type": type(e).__name__,
                   "mro": [c.__name__ for c in type(e).__mro__], "message": str(e)[:MAX_TEXT]}
        res.update(id=case["id"], duration_ms=round((time.perf_counter() - t0) * 1000, 2),
                   stdout=buf.getvalue()[:MAX_TEXT])
        emit(res)
    emit({"done": True})


if __name__ == "__main__":
    main()
