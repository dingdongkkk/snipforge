# SnipForge: requirements → Python, with test evidence

> TCS Technology Day: *Code Snippet Generator from Requirements*

SnipForge turns a plain-English feature requirement into a Python function. It makes its
**interpretation visible** and links **every requirement to executed test evidence**:

1. It writes your requirement as a numbered **contract** (R1, R2…) with explicit assumptions. Where the
   requirement is ambiguous in a way that changes behaviour, it **asks you** instead of guessing.
2. It designs **test cases from the confirmed contract only**, then **freezes** them before any code exists.
3. It generates the code (which never sees the tests), grounded in our library of verified snippets.
4. It checks syntax and policy, then runs the frozen cases in an **isolated runner**. A trusted harness
   decides pass/fail, so the generated code can't report its own status.
5. If a case fails, it makes **one bounded, code-only repair** from the real failure. The tests can't be changed.
6. It reports a **requirement → cases → outcome** table, with `not tested` and `not executed` shown honestly,
   and exports a ZIP (solution, contract, cases, a pytest file, and a report).

## After generation: challenge it, change it, test the tests

| Tab | What happens | Model calls |
|---|---|---|
| **⚡ Challenge** | An adversarial pass designs up to 10 new edge cases from the **contract only** (thresholds ±1, invalid inputs, empty/unicode, flag combinations, approved `idempotent`/`deterministic` properties). They run in the isolated runner. Failures show the input, expected vs actual, and the requirement affected. Checked cases can be kept as **regression tests**: they join the frozen set and the code is re-verified (and repaired, code only) as a new version. | 1 (+ repairs) |
| **✎ Revise** | "Keep everything else, but make free shipping start at 750." The model proposes a revised contract (unchanged / modified / added / removed per requirement), and you confirm it. Tests on unchanged requirements are **kept as regression checks**. Tests on changed requirements are replaced with new ones designed from the revised contract. The code is updated and verified as v(n+1), with a code diff against the previous version. | 3 (+ repairs) |
| **🧬 Test the tests** | Up to 5 deterministic AST mutations of the passing code (threshold `<`→`<=`, limit +1, `and`↔`or`, `+`↔`-`, drop `not`). Each runs against the frozen tests: **detected / survived / error**. A survivor points at a coverage gap (or an equivalent change). | 0 |

Every change produces a new **run version** linked to its parent. The ZIP bundle includes `history.json`
(per version: change, test changes, requirements, hashes, code), plus the challenge and mutation results in `report.md`.

## Pipeline and state machine

```
 draft ──analyze (1 call)──► needs_clarification ──answers──► contract_ready
                                     │ (proceed with provisional assumptions)        │ user confirms / edits
                                     └───────────────────────────────────────────────┤
 retrieve: top-2 verified library snippets (BM25 [+ gte-large]) ◄────────────────────┘
 design tests from CONTRACT ONLY (1 call) ─► validate schema ─► FREEZE (hash) ─► tests_ready
 generate code, never sees the tests (1 call) ─────────────────────────────────► generated
 syntax (ast) ─► policy (entry point, signature, stdlib-only, no eval/subprocess/network)
            ─► trusted harness runs frozen cases in container / isolated process ─► validated
 any fail? ─► repair: code only, same frozen cases, max 1 by default (1 call) ─► validated
 ─► passed | failed | not_executed  ─► evidence table · diff · export ZIP · recorded run
```

The model budget is **3 calls + 1 optional repair**, plus at most one schema-recovery call per phase.
Nothing runs on page re-render; every stage starts from an explicit click.

## Quick start (Python 3.12, standard library only)

```bash
cp .env.example .env          # add GROQ_API_KEY / GEMINI_API_KEY / OPENROUTER_API_KEY, or use Ollama
python server.py              # http://localhost:8000
```

* **Local SLM:** pick *Ollama* in the UI. Set `OLLAMA_MODEL` to the exact tag from `ollama list`,
  and run a dev eval before trusting it.
* **Container isolation (recommended if Docker exists):** `docker build -t snipforge-runner:1 -f runner/Dockerfile .`.
  The app detects the image automatically. Otherwise it uses an isolated `python -I` subprocess, and the UI
  says which one it's using. `SNIPFORGE_RUNNER=none` disables execution, and results then show *not executed*, never a pass.
* **No Wi-Fi on stage:** every live run is saved. *Recorded runs* replays one with a banner showing its original
  timestamp and model. It's never presented as a new live generation.
* **CLI:** `python cli.py "Implement shipping_fee(total, express) ..." --provider groq --zip out.zip`
* **Dev UI without a key:** `python scripts/dev_fixture_server.py` uses a scripted **seeded-fault** fixture,
  labelled as such in every result.

## Evaluation

```bash
python eval/run_eval.py --provider groq --set dev        # tune prompts here only
python eval/run_eval.py --provider groq                  # frozen 20-task holdout: baseline vs pipeline
```

* `data/benchmark.jsonl` (v1, frozen): 5 text + 5 list/dict + 5 numeric + 5 CSV/business-rule tasks with
  **hidden tests written and reference-checked by us** (`data/build_benchmark.py`). Hidden tests never enter
  prompts, retrieval or repair.
* Both modes run on the same tasks, model and hidden tests. **Baseline** is one direct prompt.
  **Pipeline** is the full flow, with ambiguities auto-resolved into recorded assumptions.
* Reported: functional success (tasks passing **all** hidden tests out of 20; target ≥ 16), first-attempt vs
  post-repair, syntax validity, per-category results, model calls and latency. The pipeline costs more calls,
  and the report says so.
* Results are in `eval/results/` and `docs/RESULTS.md`. A teammate scores *relevance* separately with a checklist.

## Layout

| Path | What |
|---|---|
| `snipforge/contracts.py` | RequirementContract / TestCase validation, evidence mapping, hashes |
| `snipforge/prompts.py` | Analyze, test-design, generate, repair and baseline prompts + tolerant parsers |
| `snipforge/pipeline.py` | State machine, bounded model budget, frozen tests, code-only repair |
| `snipforge/runner.py`, `harness.py` | Isolated execution (container / process / none) and trusted comparison |
| `snipforge/validator.py` | Syntax, policy gate, quality signals; test-function runner for the data builders |
| `snipforge/retriever.py` | Text normalisation, BM25 (+ optional embeddings), library growth |
| `snipforge/evolve.py` | Challenge, regression capture, requirement revisions (versioned runs) |
| `snipforge/mutation.py` | Deterministic AST mutation testing against the frozen tests |
| `snipforge/reporting.py` | pytest translation, report.md, ZIP bundle with history, recorded runs |
| `snipforge/llm.py` | One OpenAI-compatible client: Ollama, Groq, Gemini, OpenRouter, OpenAI, xAI |
| `server.py`, `static/index.html` | Web UI (stdlib HTTP + SSE) |
| `data/build_kb.py` | 38 library snippets, each verified by running its tests |
| `data/build_benchmark.py` | Dev (10) and frozen holdout (20) sets with reference-verified hidden tests |
| `eval/run_eval.py` | Baseline vs pipeline evaluation |
| `tests/` | 28 deterministic tests with a mocked model (`python -m unittest discover tests`) |
| `docs/` | Architecture, prompt design, demo script, team contributions |

## Limitations (say these out loud)

* Tests are evidence for specific cases, not proof of general correctness. The same model family writes the
  test expectations, so a person should review them (the Tests tab shows every expected value).
* The subprocess runner is a prototype boundary, and so are ordinary containers; neither is hardened multi-tenant isolation.
* Scope is single functions with JSON-compatible inputs and outputs, standard library only.
