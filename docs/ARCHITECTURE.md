# Architecture

```
 Browser (static/index.html)
   ├─ POST /api/analyze ───────────► pipeline.analyze ──► LLM (contract JSON) ──► contracts.normalize_contract
   │     ◄── contract + state (needs_clarification | contract_ready)
   ├─ user edits / answers / confirms
   ├─ POST /api/generate (SSE) ────► pipeline.run_generation
   │                                   ├─ retriever.search (library snippets, provenance shown)
   │                                   ├─ LLM test design (contract only) ─► contracts.validate_cases ─► freeze (hash)
   │                                   ├─ LLM generate (contract + snippets, never tests)
   │                                   ├─ validator.check_syntax / policy_check
   │                                   ├─ runner.execute_cases ─► [container | python -I process] harness.py
   │                                   │      parent compares results; child only reports return/raise
   │                                   └─ repair (code only) ─► re-verify against the same frozen cases
   │     ◄── stage events … result (saved to data/runs/)
   ├─ POST /api/challenge ─────────► evolve.challenge (contract-only edge cases → runner)   [attached to run]
   ├─ POST /api/regress (SSE) ─────► evolve.regress (kept cases join frozen set → verify/repair) → v(n+1)
   ├─ POST /api/revise/propose ────► evolve.propose_revision (revised contract + requirement diff)
   ├─ POST /api/revise/apply (SSE) ► evolve.run_revision (keep unaffected tests, design new, update code) → v(n+1)
   ├─ POST /api/mutate ────────────► mutation.mutation_test (≤5 AST mutants vs frozen tests)       [attached to run]
   ├─ GET /api/export/<run> ───────► reporting.bundle (ZIP incl. history.json)
   └─ GET /api/runs/<run> ─────────► recorded replay, always labelled
```

## Data contracts (`snipforge/contracts.py`)

* **RequirementContract:** `schema_version, request_id, raw_requirement, function_name, parameters[{name,type,description}],
  return_type, requirements[{id,text}], assumptions[], edge_cases[], clarification_questions[], examples[]`.
  It's revalidated server-side after the user edits it.
* **TestCase:** `id, requirement_ids[], description, args[], kwargs{}`, plus **exactly one** of `expected`
  (JSON `null` is a real expectation), `expected_exception`, or `property` (`idempotent` | `deterministic`).
  Optional `origin` (e.g. `challenge C1`). Optional `tolerance` and `strict_type`. Malformed
  cases are rejected and listed in the UI.
* **TestResult:** `test_id, status (pass|fail|error|timeout|not_executed), expected, actual, duration_ms, bounded_error`.
* **Result:** `validation{syntax, policy, results, counts, execution_mode}`, `evidence[]`, `repair_attempted`,
  `tests_unchanged`, `attempts[]`, `diff`, `hashes{code, contract, test_set}`, `model_calls`, `timings`, `prompt_version`.

## Versioning rules

* A run is immutable once saved, except that challenge and mutation results get *attached* to it.
* **Repair** never changes tests. **Regression capture** and **revision** produce a new version with
  `parent_run_id`, `change`, `test_changes {kept, removed, added}`, `version_diff`, and (for revisions) `regression`
  (how many kept tests still pass).
* Requirement IDs are stable across revisions: unchanged and modified requirements keep their ID, and new ones get the next free ID.
  A test is kept only if *every* requirement it covers is unchanged. New tests must target a changed or added requirement.
* The final code of any version is the best attempt (most frozen cases passing), so a bad repair can't replace better code.

## Comparison rules (`runner.values_equal`)

Comparison is exact at the JSON level. `True ≠ 1`, `None ≠ 0`, and a returned value is never equal to a raised exception.
Integers and floats compare by value unless the case sets `strict_type` (e.g. "return an integer").
Floats are compared with a tolerance only when the case sets one. The harness converts return values the way JSON does:
tuples become lists, sets become sorted lists, and dict keys become strings. Each case gets a fresh deep copy of its
inputs, so mutating an argument can't leak into the next case.

## Execution boundary

* The generated code **never** runs in the server process.
* **Container mode** (when the `snipforge-runner:1` image exists): `--network none --read-only --cap-drop ALL
  --security-opt no-new-privileges --user 65534 --memory 256m --cpus 1 --pids-limit 64 --tmpfs /tmp:16m,noexec`,
  with no mounts. The job goes in over stdin. On a wall-clock timeout the container is force-removed.
* **Process mode:** `python -I` in a throwaway temp dir, with a stripped environment, RLIMIT_CPU, a 1 GB memory limit
  on Linux, and a timeout.
* **Trusted comparison:** expected values are never sent to the child. The child prints results prefixed with a random
  per-run nonce, and the parent decides pass/fail. A crash, a missing `done` marker, malformed output or a timeout all
  fail closed. A unit test checks that code which prints fake results can't forge a pass.
* This is a prototype boundary. Neither mode is hardened multi-tenant isolation.

## Scaling path

| Now | Production |
|---|---|
| stdlib HTTP server, per-request SSE | API service + job queue; runner jobs on a separate worker pool with per-job quotas |
| local Docker / subprocess runner | gVisor/Firecracker sandboxes, artifact storage for bundles |
| JSONL library + BM25 | pgvector/FAISS hybrid search over internal repos with provenance |
| one provider per request | provider rate limiting, fallbacks, cost tracking |
| Python functions | language-pluggable harness (`tsc`/`javac`/`dotnet test`), VS Code extension, Jira intake |
