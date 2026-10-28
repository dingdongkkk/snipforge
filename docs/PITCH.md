# SnipForge: the pitch

## The one-liner (memorise this)

> **"AI can already write code. The problem is trusting it. SnipForge turns a requirement into Python code that
> comes with a receipt: what it understood, the tests that prove it, and evidence for every requirement."**

---

## 3-minute script

| Time | On screen | Say (roughly) |
|---|---|---|
| **0:00–0:20** | Title slide | "Developers spend hours turning written requirements into boilerplate. AI tools write code fast, but you still have to read every line to know whether it did what you *meant*. We built SnipForge to make AI code **reviewable in a minute**." |
| **0:20–0:50** | Click chip **Business-rule boundaries** → **Analyze** | "First it writes down its interpretation: numbered requirements, R1 to R5, plus its assumptions. You can edit them before any code exists. The function name and parameters in your requirement are binding, so the model can't invent its own." |
| **0:50–1:25** | **Confirm & generate**, then watch the Pipeline panel | "Now the key idea: **tests are written from the requirements before the code exists, then frozen**. The model writing the code never sees them. We generate three independent implementations and cross-check them. Everything runs in an isolated sandbox, and **our** harness decides pass or fail, not the AI." |
| **1:25–1:50** | **Requirement evidence** tab, then **Tests** tab | "Every requirement is linked to the tests that prove it: 499 gives 40, 500 gives 0. If something isn't tested, it says *not tested*. We deliberately don't show a made-up confidence score." |
| **1:50–2:15** | Chip **Ambiguous (clarify)** → **Analyze**, then pick an option | "When a requirement is vague, it doesn't guess. It asks a **multiple-choice question**: which field identifies a duplicate, and which record to keep. One click, and the answer becomes a requirement." |
| **2:15–2:35** | Back on shipping: **✎ Revise** "make free shipping start at 750" | "Requirements change. It shows exactly which requirement changed, **keeps the old tests as regression checks**, and shows the one-line code diff." |
| **2:35–2:45** | **🧬 Test the tests** | "And how do we know the tests are any good? We deliberately plant bugs. **The tests caught 5 out of 5.**" *(read the real number)* |
| **2:45–3:00** | Results slide | "On our 20-task benchmark with hidden tests, we hit **20/20**, against an 80% target. It works with any model, including local ones. Thank you." |

If you run short, cut **Revise** first, then **Ambiguous**. Never cut the evidence table.

---

## Which features to explain (priority order)

### Must show (the core story)
1. **Contract first.** Numbered requirements plus assumptions, editable before code. *Why it matters:* you see the AI's interpretation instead of reverse-engineering it from code.
2. **Tests before code, frozen.** Designed from requirements only; the code model never sees them; repair can change code only (hash-checked). *Why it matters:* the AI can't "pass" by quietly changing the tests, which AI coding agents are known to do.
3. **Requirement evidence table.** R1 → T1, T5 → passed. "Not tested" and "disputed" are shown honestly. *Why it matters:* a reviewer checks one table instead of reading all the code.
4. **Multiple-choice clarification.** When something is ambiguous, it asks with options, a recommendation, and an "Other" box. *Why it matters:* it doesn't silently guess business rules.

### Show if time allows
5. **🧬 Test the tests (mutation testing).** Plant small bugs, see which the tests catch, no AI calls. Strongest technical point.
6. **✎ Revise.** Versioned requirements; unchanged tests kept as regression checks; code diff v1 → v2.
7. **⚡ Challenge.** An adversarial pass designs edge cases from the requirements only; failures can be kept as regression tests.

### Mention in one sentence each
8. **Cross-check:** three independent implementations; tests they all agree against get flagged as *disputed* for review.
9. **Safe execution:** generated code never runs in the app; it runs in an isolated sandbox (or a Docker container), with dangerous calls blocked.
10. **Any model:** Groq, OpenRouter, Gemini, OpenAI, xAI, or **local Ollama** (data stays on-prem). A different model can write the tests.
11. **Export bundle:** code, contract, tests, a runnable pytest file, a report, and version history in one ZIP.
12. **Recorded runs:** replay of earlier runs, clearly labelled, as a Wi-Fi fallback.

---

## Which test results to show (one slide)

**Slide: "Measured, not claimed"**

| What | Result |
|---|---|
| 20-task holdout benchmark, hidden tests written by us (5 text, 5 list/dict, 5 numeric, 5 CSV/business rules) | **20/20 functional correctness** (target: ≥ 16/20 = 80%) |
| Real bug caught by the pipeline itself | `parse-duration`: first draft wrong → its own tests caught it → code-only repair fixed it |
| Bug our eval found **in our own pipeline**, then fixed | The model renamed `shipping_fee` → `calculate_shipping_fee` (correct code, wrong name). Fixed: names in the requirement are now binding. Dev set: 3/10 → 9/10 |
| Mutation testing on the demo function | Tests caught 5 of 5 planted bugs (show the live number) |
| Engineering quality | 42 automated tests, including adversarial ones: generated code **cannot forge a pass**, repair **cannot edit tests**, a timeout or crash is **never a pass** |

**Say this sentence about accuracy, because it builds trust:**
> "A strong model with a single prompt also scored 20/20 on these tasks. So our claim isn't 'more correct code'.
> It's code you can **verify and own**: interpretation, independent tests, and evidence for every requirement."

### What NOT to claim
- ❌ "SnipForge makes small/local models more accurate." **We measured the opposite:** on 3–4B models, a plain
  prompt scored 16–17/20, and our best pipeline so far is about 16/20 (Gemma) and lower on Llama. It's still being worked on.
- ❌ "The tests prove the code is correct." They're evidence for specific cases.
- ❌ "Production-grade sandbox." It's a prototype isolation boundary.

If a judge asks about small models, this answer turns it into a strength:
> "We tested on the same 3B and 4B models TCS preinstalled. We found that a small model's own tests share its
> misunderstandings, so trusting them can make things worse. That's why we added a trust policy: tests from a
> small model are evidence only, and we recommend a stronger independent model for test design. We measured it
> instead of assuming."

---

## Suggested slides (5)
1. **Title:** SnipForge, requirements to Python with test evidence. Team names.
2. **Problem:** AI writes code fast; reviewing and trusting it is the bottleneck.
3. **How it works:** the pipeline diagram (Contract → Tests (frozen) → 3 implementations → Sandbox → Evidence), plus Challenge / Revise / Test the tests.
4. **Live demo:** switch to the app.
5. **Results + limits + team:** the results table above, three limitations, who built what.

---

## Mapping to the judging criteria (for your own confidence)

| Criterion | Weight | What earns it |
|---|---|---|
| Relevance | 30 | NL requirement → executable Python, simple UI, syntax validation, prompt docs, **measured 20/20 vs the 80% target** |
| Innovation | 15 | Tests-before-code with frozen hash, multiple-choice clarification, mutation testing, regression-safe revisions, disputed-test detection |
| Feasibility & scale | 15 | No installs, any provider incl. local, sandboxed runner, Docker option, versioned runs, export bundle |
| AI/ML/GenAI | 20 | Prompt engineering, RAG over verified snippets, multi-model test design, CodeT-style consensus, self-repair, eval harness with baseline |
| Teamwork | 20 | **Fill in `docs/team_contributions.md`** and say who built what on the last slide |

---

## Judge Q&A (short answers)

- **"How is this different from ChatGPT or Copilot?"** They give you code; we give you code plus the evidence to trust it: stated interpretation, independent frozen tests, a per-requirement result, and safe execution. We can use their models as the engine.
- **"Can't the AI just change the tests?"** No. The tests are frozen before the code exists, repair is code-only, and the test set is hash-checked.
- **"Who checks the tests?"** You do, in one table. Disputed ones are flagged. Mutation testing shows whether the tests catch bugs.
- **"Is it slow?"** About 20s and 4–6 model calls versus about 2s for one prompt. You pay seconds to save review time.
- **"Does it work offline / on-prem?"** Yes, with Ollama and local models. For best results, have a stronger model design the tests.
