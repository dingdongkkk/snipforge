"""SnipForge web server (stdlib only). Run: python server.py  ->  http://localhost:8000"""
from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from snipforge import evolve, pipeline, reporting
from snipforge.mutation import mutation_test
from snipforge.config import DEFAULT_PROVIDER, MAX_REPAIRS, TEST_MODEL, TEST_PROVIDER, public_providers
from snipforge.runner import execution_mode

STATIC = Path(__file__).parent / "static"
DEMOS = [
    {"label": "Stable dedup", "requirement": "Implement unique_emails(emails). Strip whitespace and lowercase each "
     "string, remove empty strings, remove duplicates while preserving first-seen order. Raise ValueError if any "
     "element is not a string. Empty list returns []."},
    {"label": "Business-rule boundaries", "requirement": "Implement shipping_fee(total, express). Reject negative "
     "totals with ValueError. Standard shipping costs 40 below 500 and 0 at or above 500. Express adds 60 to the "
     "standard fee. Return an integer for integer inputs."},
    {"label": "Ambiguous (clarify)", "requirement": "Clean customer records and remove duplicates."},
    {"label": "India: GSTIN", "requirement": "Write a function that checks whether a string is a valid Indian GSTIN "
     "format and returns True or False."},
    {"label": "CSV totals", "requirement": "Given CSV text with columns region,amount return a dict of total amount "
     "per region rounded to 2 decimals. Raise ValueError if a column is missing."},
]


def parse_examples(text) -> list[dict]:
    """'[499, false] => 40' per line -> [{"args": [...], "expected": ...}]. Raises ValueError."""
    if isinstance(text, list):
        return text
    out = []
    for i, line in enumerate((text or "").splitlines(), 1):
        if not line.strip():
            continue
        if "=>" not in line:
            raise ValueError(f"example line {i}: use  [args] => expected")
        left, right = line.split("=>", 1)
        try:
            args = json.loads(left.strip())
            expected = json.loads(right.strip())
        except json.JSONDecodeError as e:
            raise ValueError(f"example line {i}: values must be JSON ({e.msg})") from e
        out.append({"args": args if isinstance(args, list) else [args], "expected": expected})
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "SnipForge/2.0"

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {fmt % args}\n")

    def _send(self, body: bytes, ctype: str, status=200, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(json.dumps(obj).encode(), "application/json", status)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n > 2_000_000:
            raise ValueError("request too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send((STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/config":
            return self._json({"providers": public_providers(), "default_provider": DEFAULT_PROVIDER,
                               "max_repairs": MAX_REPAIRS, "demos": DEMOS,
                               "test_provider": TEST_PROVIDER, "test_model": TEST_MODEL,
                               "fixture": os.getenv("SNIPFORGE_FIXTURE") == "1", "execution_mode": execution_mode(),
                               "kb_size": len(pipeline.get_retriever().items), "runs": reporting.list_runs()})
        if self.path.startswith("/api/runs/"):
            run = reporting.load_run(self.path.rsplit("/", 1)[-1])
            return self._json(run) if run else self._json({"error": "run not found"}, 404)
        if self.path.startswith("/api/export/"):
            run = reporting.load_run(self.path.rsplit("/", 1)[-1])
            if not run:
                return self._json({"error": "run not found"}, 404)
            name = f"{run['contract']['function_name']}_snipforge.zip"
            return self._send(reporting.bundle(run), "application/zip",
                              extra={"Content-Disposition": f'attachment; filename="{name}"'})
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        try:
            body = self._body()
        except (ValueError, json.JSONDecodeError):
            return self._json({"error": "invalid JSON body"}, 400)
        provider = body.get("provider") or DEFAULT_PROVIDER
        model = (body.get("model") or "").strip() or None
        # "" = tests by the same model as the code; omitted = server default (SNIPFORGE_TEST_PROVIDER)
        tests = {"test_provider": body.get("test_provider"), "test_model": (body.get("test_model") or "").strip()
                 if body.get("test_provider") is not None else None}
        if self.path == "/api/analyze":
            try:
                examples = parse_examples(body.get("examples"))
                res = pipeline.analyze(body.get("requirement", ""), provider, model,
                                       function_name=(body.get("function_name") or "").strip() or None,
                                       examples=examples, answers=body.get("answers") or None)
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            except pipeline.PipelineError as e:
                return self._json({"error": str(e)}, 502)
            return self._json(res)
        if self.path == "/api/generate":
            return self._stream(pipeline.run_generation(body.get("contract") or {}, provider, model,
                                                        max_repairs=self._repairs(body), **tests))
        if self.path in ("/api/challenge", "/api/regress", "/api/revise/propose", "/api/revise/apply", "/api/mutate"):
            run_id = body.get("run_id", "")
            run = reporting.load_run(run_id, replay=False)
            if not run:
                return self._json({"error": "run not found"}, 404)
            try:
                if self.path == "/api/challenge":
                    ch = evolve.challenge(run, provider, model, **tests)
                    reporting.attach(run_id, "challenge", ch)
                    return self._json(ch)
                if self.path == "/api/mutate":
                    mu = mutation_test(run)
                    reporting.attach(run_id, "mutation", mu)
                    return self._json(mu)
                if self.path == "/api/revise/propose":
                    return self._json(evolve.propose_revision(run, body.get("change", ""), provider, model,
                                                              answers=body.get("answers") or None))
            except (pipeline.PipelineError, ValueError) as e:
                return self._json({"error": str(e)}, 400)
            if self.path == "/api/regress":
                return self._stream(evolve.regress(run, run_id, body.get("case_ids") or [], provider, model,
                                                   max_repairs=self._repairs(body)))
            return self._stream(evolve.run_revision(run, run_id, body.get("contract") or {}, body.get("change", ""),
                                                    provider, model, max_repairs=self._repairs(body), **tests))
        if self.path == "/api/accept":
            run = reporting.load_run(body.get("run_id", ""))
            if not run or run["status"] != "passed":
                return self._json({"error": "only passed runs can be added to the library"}, 400)
            r = pipeline.get_retriever()
            r.add({"id": f"user-{run['contract']['function_name']}-{int(time.time())}",
                   "requirement": run["contract"]["raw_requirement"], "tags": ["user-accepted"],
                   "code": run["code"], "tests": reporting.pytest_file(run)})
            return self._json({"ok": True, "kb_size": len(r.items)})
        self._json({"error": "not found"}, 404)

    @staticmethod
    def _repairs(body: dict) -> int:
        try:
            return max(0, min(int(body.get("max_repairs", MAX_REPAIRS)), 3))
        except (TypeError, ValueError):
            return MAX_REPAIRS

    def _stream(self, events):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def send(ev):
            self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
            self.wfile.flush()

        try:
            for ev in events:
                if ev["type"] == "result":
                    ev["run_id"] = reporting.save_run(ev)
                send(ev)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # surface unexpected errors instead of a dead stream
            send({"type": "error", "message": repr(e)})


def main(port: int = 8000):
    pipeline.get_retriever()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"SnipForge running at http://localhost:{port}  (execution: {execution_mode()})  Ctrl+C to stop")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8000)
