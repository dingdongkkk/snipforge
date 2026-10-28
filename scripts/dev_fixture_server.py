"""Developer-only: run the UI against the scripted SEEDED-FAULT fixture (no API key needed).

Results show model "scripted-fixture (seeded fault)" so they can never pass for live generation.
    python scripts/dev_fixture_server.py 8001
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
os.environ.setdefault("SNIPFORGE_RUNS_DIR", str(ROOT / "data" / "runs_fixture"))

import server  # noqa: E402
from fake_llm import ScriptedClient  # noqa: E402
from snipforge import pipeline, reporting  # noqa: E402

pipeline.LLMClient = ScriptedClient
reporting.RUNS_DIR = Path(os.environ["SNIPFORGE_RUNS_DIR"])

if __name__ == "__main__":
    server.main(int(sys.argv[1]) if len(sys.argv) > 1 else 8001)
