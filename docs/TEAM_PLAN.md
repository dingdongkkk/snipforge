# Team plan and demo script

## Ownership (4 people; merge roles if you're 3)

| Role | Owns | On the day |
|---|---|---|
| **GenAI lead** | `prompts.py`, `pipeline.py`, `llm.py` | Pick and smoke-test the provider; tune prompts on the **dev** set; fill the prompt log |
| **Eval & data** | `data/`, `eval/` | Review benchmark expectations; run baseline vs pipeline on the holdout; build the results slide |
| **Runner & safety** | `runner.py`, `harness.py`, `contracts.py`, `tests/` | Build the Docker image if Docker exists; keep tests green; try to break the evidence table |
| **UI & story** | `static/index.html`, `docs/`, deck, video | Rehearse the three demo flows; record the video; keep `docs/team_contributions.md` honest |

Each person reviews one other person's area. Record who reviewed what.

## Three-minute demo

| Time | What to show |
|---|---|
| 0:00–0:20 | Problem: hand-translating requirements to boilerplate is slow and inconsistent. Promise: code **with evidence**. |
| 0:20–0:55 | **Stable dedup** demo: Analyze shows the contract R1…Rn and the assumptions. Edit one requirement live, then Confirm. |
| 0:55–1:35 | Pipeline runs: tests frozen (show the hash), code generated, cases executed. **Requirement evidence** tab: every R row passed. Tests tab: expected vs actual. |
| 1:35–2:05 | **Shipping fee** boundaries: 499 → 40, 500 → 0, express. If a real failure happened, show the repair diff and *frozen tests unchanged: yes*. If you use the fixture, **say it's a seeded fault**. |
| 2:05–2:20 | **"Clean customer records"**: the app asks which field identifies a duplicate and which record to keep. Answer and show the updated contract. |
| 2:20–2:35 | On shipping_fee: **✎ Revise** "make free shipping start at 750". Show the requirement diff, the regression-check count for unchanged behaviour, and the v1→v2 code diff. |
| 2:35–2:45 | **🧬 Test the tests**: read out the real "detected N of M" line. If one survives, that's the coverage-gap story. **⚡ Challenge** if time allows. |
| 2:45–3:00 | Actual benchmark table (baseline vs pipeline, calls/latency), architecture slide, limitations, who did what. |

Recording checklist: provider configured, execution badge shows container/process (not unavailable), browser zoom 110%,
the recorded-runs fallback ready, and if a recorded run is used, show its banner on screen.

## Likely judge questions

* **"Couldn't it just change the tests to pass?"** No. Tests are frozen before code exists, repair is code-only, and
  the pipeline checks the test-set hash afterwards.
* **"Who checks the tests?"** A person does: every expected value is visible in the Tests tab. For measurement we use
  hidden tests that we wrote ourselves and the model never sees.
* **"Is running model code safe?"** It never runs in the app process. It runs in a no-network, read-only, capability-dropped
  container (or an isolated process), and the parent decides pass/fail. It's a prototype boundary, and we say so.
* **"How do you know the tests are any good?"** Mutation testing: we deliberately break the code and check whether the
  tests notice. Survivors are reported, not hidden.
* **"What happens when requirements change?"** Revise: a versioned contract, unchanged tests kept as regression checks,
  and a code diff against the previous version.
* **"Is 80% real?"** Show the measured number from `eval/results/`, whatever it is.
