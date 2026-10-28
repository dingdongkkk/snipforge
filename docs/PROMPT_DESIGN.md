# Prompt design (prompt v2.1)

All prompts are in `snipforge/prompts.py`. They're designed to work with both a 3B local SLM and a 70B
hosted model. Every model output is validated locally before use. No chain-of-thought is requested.

| Step | Sees | Returns | temp |
|---|---|---|---|
| Analyze | requirement, optional name/examples, user's answers | contract JSON | 0.0 |
| Test design | **confirmed contract only** | `{"test_cases": [...]}` | 0.0 |
| Generate | confirmed contract + ≤2 library snippets (**never the tests**) | EXPLANATION / LIMITATIONS / CODE | 0.2 |
| Repair | contract + current code + failing case evidence | same format, **code only** | 0.1 |
| Challenge | contract + already-tested inputs (**never the code**) | `{"test_cases": [...]}` ≤10, may use approved properties | 0.0 |
| Revise contract | current contract + change request | full contract, requirements as `{source_id, text}` | 0.0 |
| Revision tests | revised contract, `only_ids` = changed/added, kept inputs | cases targeting changed requirements only | 0.0 |
| Revision code | revised contract + current code + change (never tests) | EXPLANATION / LIMITATIONS / CODE | 0.2 |
| Baseline (eval only) | raw requirement | code | 0.2 |

## Why each design choice

* **Contract first.** A vague requirement becomes 2–8 numbered, atomic, testable requirements. The model is told
  not to invent business rules. If a missing detail changes behaviour, it must ask a clarification question
  *and* record a provisional assumption. The UI shows both, the user answers or edits, and the contract is regenerated
  with the answers turned into explicit requirements.
* **Independent test design.** Test cases are written from the contract alone, before any code exists, so the test
  writer can't simply copy the implementation's mistakes. The cases are declarative JSON (args, expected or
  expected_exception, requirement_ids), which a trusted harness can check without executing model-written test code.
  The prompt requires every requirement to be covered and forbids testing behaviour the contract leaves open.
  This lowers correlated errors but doesn't remove them, since the same model family writes both.
* **Generation never sees the tests**, so it can't overfit to them. It does see two verified library snippets
  for house style, with an instruction not to copy them blindly.
* **Repair is code-only.** The prompt states the contract and cases are frozen. The pipeline also re-checks the test-set
  hash after repair and aborts if it changed. Feedback is compact: case id, linked requirements, call, expected,
  actual, error.
* **Markdown sections for code, JSON for structure.** Escaping code inside JSON strings is a common way for small
  models to fail, so code comes back in a fenced block, while the contract and tests come back as JSON.
* **Schema recovery.** If JSON doesn't parse, one recovery call sends the bad output back with the error.
  `parse_json` also extracts the JSON object from surrounding chatter and repairs trailing commas.
* **Explicit names are binding.** If the requirement spells out `name(...)`, that name is passed to the analyst
  and enforced. (Dev eval finding: the model had renamed `shipping_fee` to `calculate_shipping_fee`, which made correct
  code fail every hidden test.)
* **Challenge without the code.** The adversarial pass sees only the contract and the inputs already tested, so its
  expected values come from the contract, not from guesses about the implementation. Duplicate inputs are dropped.
* **Revisions with `source_id`.** The model maps each revised requirement to the one it keeps or modifies. Requirement IDs stay
  stable, so tests on unaffected requirements are kept as regression checks.
* **No confidence percentage.** Status is shown as syntax, policy, execution mode, cases passed, and requirements evidenced.

## Integration

All six providers use one OpenAI-compatible `/chat/completions` client (`llm.py`), with no SDKs. Retries with
backoff cover 429/5xx responses. Credentials come from the environment and are never logged or shown.

## Prompt iteration log (dev set only; fill in on the day)

| Change | dev first-attempt | dev post-repair |
|---|---|---|
| v2.0 (Groq gpt-oss-120b) | 4/10* | 3/10* (*5 tasks lost to HTTP 429 rate limits) |
| + binding explicit function names, best-attempt selection, 429 retry/key rotation | 9/10 | 9/10 (1 lost to a dropped connection, now retried) |
| Direct-prompt baseline, same model | 10/10 | n/a |
