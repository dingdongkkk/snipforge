# SnipForge: demo handoff

> **One line:** SnipForge turns a plain-English requirement into a Python function, and shows the evidence that it
> works. Each requirement is linked to tests that were written *before* the code and actually executed. You can then
> attack it, change it, and check whether the tests themselves are any good.

---

## 1. Start it (2 minutes before you present)

```bash
cd ~/Downloads/codesnippet
.venv/bin/python server.py      # open http://localhost:8000 (the .venv has pytest, pylint, pypdf)
```

**Pre-demo checklist**
- [ ] The header badge says **execution: isolated process** (or *container*), not *unavailable*.
- [ ] The provider dropdown shows **OpenRouter** with model `openai/gpt-oss-120b` (now the default in `.env`).
  **Groq** is faster, but its free tier allows only 200k tokens per day, and our benchmarks used it all on Oct 28.
  Only switch back once it has reset. **Gemini** is a slow last resort.
- [ ] Do one warm-up run of the shipping demo, so a **recorded run** exists as a Wi-Fi fallback.
- [ ] Browser zoom at 110%, window wide enough for two columns.

Keys are in `.env`: Groq (2 keys, rotated automatically on rate limits), OpenRouter, Gemini.
⚠️ They were pasted into a chat, so **rotate them after the hackathon**.

---

## 2. The pipeline (what to draw on the slide)

```
Requirement ─► ① Contract ─► ② Tests (from contract only, then FROZEN) ─► ③ Code (never sees tests)
                 │ asks you if ambiguous                                          │
                 ▼                                                                ▼
          you confirm/edit                   ④ Validate: syntax · policy · isolated execution
                                                     │ fail?
                                                     ▼
                                     ⑤ Repair: CODE ONLY, same frozen tests (max 1)
                                                     ▼
                         ⑥ Evidence table · Export ZIP · saved as a versioned run
                                                     ▼
              ⚡ Challenge it    ✎ Revise it (v2, v3…)    🧬 Test the tests
```

Model calls per snippet: **3 + at most 1 repair**. Any model on the TCS list works through one client
(Ollama, Groq, Gemini, OpenRouter, OpenAI, xAI).

---

## 3. Features: what to click, what to say

### ① Contract with clarification (Relevance, GenAI)
**Click:** pick a demo chip, then **Analyze**.
**You see:** numbered requirements R1…Rn, assumptions, and an editable list.
**Say:** "Before writing any code it states its interpretation. If something is ambiguous in a way that changes
behaviour, it asks instead of guessing."
**Ambiguity demo (multiple choice):** chip **Ambiguous (clarify)**, "Clean customer records and remove duplicates".
The model asks **multiple-choice questions**: 2–4 concrete options each, the recommended one preselected, a one-line
"why it matters", and an **Other** box for a free-text answer. Pick a *non*-recommended option and click
**Update with answers**. The picks become explicit requirements (live example: picking "most recent `updated_at`"
produced R3 "the record with the most recent valid updated_at is retained", plus tie and missing-timestamp rules).
**Say:** "It doesn't guess on decisions that change behaviour. It asks, and a question is one click to answer."
The same multiple-choice questions appear in **✎ Revise** when a change request is ambiguous. In non-interactive
runs (CLI/eval), the recommended option is taken automatically and recorded as an assumption.

### ② Tests first, frozen (Innovation)
**Click:** **Confirm & generate**, and watch the Pipeline panel.
**Say:** "Tests are designed from the contract alone, before any code exists, then frozen with a hash. The code
generator never sees them, so it can't write code to fit the tests."
**Show:** the **Tests** tab: every case, its requirement, the expected value and the actual value.

### ③ Isolated execution + trusted harness (Feasibility, Safety)
**Say:** "Generated code never runs inside the app. It runs in a separate locked-down process, or a no-network Docker
container. Expected values are never sent there. Our own harness decides pass/fail, so the code can't report its own result."
Dangerous code (`subprocess`, `eval`, network) is blocked and shown as **not executed**, never as a pass.

### ④ Requirement evidence table (Relevance)
**Show:** the **Requirement evidence** tab: R1 → T1, T5 → passed.
**Say:** "Every requirement maps to the tests that prove it. If nothing tests a requirement, it says *not tested*.
We don't show an invented confidence score."

### ⑤ Code-only repair
If a test fails, the model gets the exact failing input, expected value and actual value, and fixes **the code only**.
The status shows *frozen tests unchanged: yes*. The Code tab has a **Repair diff** button.
If the live model gets it right first time, there's no repair to show. That's fine; say so.

### ▶ Run: instant playground (fastest thing to show)
**Click:** the **▶ Run** tab. The inputs are prefilled from a test case. Type any value (JSON: `500`, `true`, `"text"`, `[1,2]`)
and press **⌘/Ctrl+Enter**. The return value, exception, and `print` output appear in milliseconds, with **no AI call**,
in the same isolated sandbox. You can edit the code, then click **Run frozen tests** to re-check it against the frozen tests.
**Demo trick:** introduce a bug on purpose (e.g. change `< 500` to `<= 500`), run the frozen tests, and watch them catch it.

### ⬆ Upload + pytest + pylint
- **Upload:** click **⬆ Upload requirement** or drop a .txt/.md/.docx/.pdf/image on the requirement box. Images go
  through Tesseract OCR. The text lands in the box for you to review before Analyze.
- **pytest + pylint:** every run ends with a real `pytest` run of the frozen tests (exported as `test_solution.py`)
  and a pylint score. Both show in the Pipeline panel and at the top of the **Tests** tab, and in the ▶ Run tab you can
  re-run them on edited code. **Say:** "We don't just trust our own checker: the same tests run under real pytest,
  and pylint scores the code."

### ⑥ ⚡ Challenge this snippet (new)
**Click:** the **⚡ Challenge** tab, then **Challenge this snippet**.
**You see:** up to 10 new edge cases (threshold ±1 like 499.99 / 500.0 / 500.01, invalid inputs, odd flags, properties
such as "running it twice gives the same answer"). A failure shows as a red banner: *input, expected vs actual,
requirement affected*.
**Say:** "It tries to break its own code. The attacker only sees the contract, so its expectations come from the
requirements, not from the code."
**Then:** tick a case and click **Keep as regression tests**. It joins the frozen tests, the code is re-verified, and
the result is saved as **v2**.

### ⑦ ✎ Revise a requirement (new, the strongest "real workflow" moment)
**Click:** the **✎ Revise** tab, type *"Keep everything else, but make free shipping start at 750."*, then **Propose revised contract**.
**You see:** each requirement marked **unchanged / modified (was: …) / added / removed**. Then **Confirm revision**.
**Result:** **v2**, with a banner showing *tests kept / removed / added* and *regression checks on unchanged behaviour: X/Y pass*.
The Code tab has a **Change vs v1** diff, which should be just the threshold line.
**Say:** "Requirements change. Tests on unchanged behaviour are kept as regression checks, and only the changed
parts get new tests. Contract, tests and code are versioned together."

### ⑧ 🧬 Test the tests (new, the strongest technical point)
**Click:** the **🧬 Test the tests** tab, then **Test the tests** (needs a passing version, and makes no model calls).
**You see:** *"Tests detected N of M mutations"*, plus a table of small deliberate bugs (`< 500` → `<= 500`,
limit 500 → 501, `and` → `or`…) showing which test caught each one.
**Say:** "Passing tests only matter if they'd catch a bug. We plant bugs and check. A survivor points to a coverage
gap, though some changes don't alter behaviour, so we call it a gap to review, not a defect."

### ⑨ Export + recorded runs
- **⬇ Download bundle:** `solution.py`, `contract.json`, `test_cases.json`, a runnable `test_solution.py` (pytest),
  `report.md` (evidence, challenge, mutation), and `history.json` (every version).
- **Recorded runs** dropdown: replays any earlier run with a banner showing *"Recorded run … not a new live
  generation"*. Use it if the network dies.

---

## 4. Three-minute script

| Time | Do | Say |
|---|---|---|
| 0:00 | Title slide | "Developers hand-translate requirements to boilerplate: slow and inconsistent. We generate code **with evidence**." |
| 0:20 | Chip **Business-rule boundaries** → Analyze | "It writes the requirement as numbered, testable rules first." |
| 0:40 | Confirm & generate | "Tests from the contract only, frozen. Code never sees them. It runs isolated." |
| 1:10 | Evidence tab → Tests tab | "Every requirement is linked to real executed tests: 499 → 40, 500 → 0." |
| 1:30 | ✎ Revise → "free shipping at 750" | "Requirements change: the diff, kept regression tests, and the v1→v2 code diff." |
| 2:00 | 🧬 Test the tests | "Are the tests any good? We plant bugs: N of M caught." |
| 2:15 | Chip **Ambiguous** → Analyze | "When it's unclear, it asks instead of guessing." |
| 2:30 | Results slide | Numbers below, limitations, who built what. |

Requirement texts (all are on the chips):
- **Boundaries:** `Implement shipping_fee(total, express). Reject negative totals with ValueError. Standard shipping costs 40 below 500 and 0 at or above 500. Express adds 60 to the standard fee. Return an integer for integer inputs.`
- **Dedup:** `Implement unique_emails(emails). Strip whitespace and lowercase each string, remove empty strings, remove duplicates while preserving first-seen order. Raise ValueError if any element is not a string. Empty list returns [].`
- **Ambiguous:** `Clean customer records and remove duplicates.`

---

## 5. Measured results (real runs, Groq `openai/gpt-oss-120b`)

| Set | Direct single prompt | SnipForge pipeline |
|---|---|---|
| Dev (10 tasks, used for tuning) | 10/10 | **9/10**; the 1 miss was a dropped network connection (now retried) |
| Holdout (20 frozen tasks, hidden tests) | **20/20** (1 call, 2.3s avg) | **20/20** (3.3 calls, 21.7s avg). On `parse-duration` the first draft was wrong; its own tests caught it and repair fixed it |

Details: [RESULTS.md](RESULTS.md).

**How to present this honestly (judges will respect it):**
- Target ≥ 80% functional correctness: **met** by both on our benchmark.
- With a strong model, a single prompt already solves these small functions, so **accuracy is not the differentiator**.
  SnipForge costs about 3 calls and 15–20s instead of 1 call and 2s.
- What the plain prompt **doesn't** give you: a visible interpretation, clarification questions, tests written
  independently before the code, requirement-level evidence, safe execution, regression-safe revisions, and proof
  that the tests catch bugs. That's the pitch.
- Real bug the eval caught *in our own pipeline*: the model renamed `shipping_fee` → `calculate_shipping_fee`.
  The code was correct but uncallable. We fixed it by making names in the requirement binding. This is a good
  "we measured and improved" story.

---

## 6. Judge Q&A

| Question | Answer |
|---|---|
| Can't it just change the tests to pass? | No. Tests are frozen before code exists, repair is code-only, and the test-set hash is checked after repair. |
| Who checks the expected values? | A person: every expected value is visible in the Tests tab. For measurement we use hidden tests we wrote ourselves. |
| Is running AI code safe? | It never runs in the app. It runs in an isolated process or a no-network, read-only Docker container, and our harness judges the result. Prototype-grade, and we say so. |
| Are the tests any good? | Mutation testing: we plant bugs and show how many the tests catch. |
| What if requirements change? | Revise: versioned contract, kept regression tests, code diff. |
| Why not fine-tune? | The brief asks for prompting + retrieval. A verified snippet library (38 examples) grounds the style, and new accepted snippets help immediately. |
| Does it scale? | Stateless, provider-agnostic API. The runner becomes a job queue with containers, and the library becomes a vector DB. See `docs/ARCHITECTURE.md`. |
| Local model? | Yes: switch the dropdown to Ollama (Qwen-coder). Same pipeline, fully on-premise. |

---

## 7. Limitations (say them before a judge does)
- Tests are evidence for specific cases, not proof of correctness. The same model family writes the tests.
- Scope: single Python functions, JSON-compatible inputs/outputs, standard library only.
- The process sandbox is a prototype boundary. Docker mode is stronger but wasn't tested on this machine (Docker isn't installed).
- Gemini's newest models return "high demand" errors. Use Groq or OpenRouter live.

---

## 8. If something breaks on stage

| Problem | Fix |
|---|---|
| Rate-limited / slow | OpenRouter is the default. If Groq has reset, it's faster. Both Groq keys are in the same org, so they share the daily limit. |
| No internet | **Recorded runs** dropdown: replay the warm-up run (the banner shows it's a recording). |
| Need to show repair/challenge findings without a live failure | `python3.12 scripts/dev_fixture_server.py` (port 8001) uses a **seeded-fault fixture**. Say out loud that it's a planted bug. |
| Anything else | `python3.12 -m unittest discover tests` should print `OK` (28 tests). |

---

## 9. Where things are

| Path | What |
|---|---|
| `server.py`, `static/index.html` | Web app (no installs needed) |
| `snipforge/pipeline.py` | Contract → tests → code → verify → repair |
| `snipforge/evolve.py` | Challenge, regression capture, revisions |
| `snipforge/mutation.py` | Test the tests |
| `snipforge/runner.py`, `harness.py` | Isolated execution + trusted pass/fail |
| `eval/run_eval.py` | `python3.12 eval/run_eval.py --provider groq` (baseline vs pipeline) |
| `docs/` | Architecture, prompt design, team plan, **team_contributions.md (fill this in, it's 20% of the score)** |
