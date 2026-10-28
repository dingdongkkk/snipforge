"""Prompt templates and tolerant parsers. See docs/PROMPT_DESIGN.md for the reasoning."""
from __future__ import annotations

import json
import re

PROMPT_VERSION = "2.2"

ANALYZE_SYSTEM = """You are a senior software analyst. Turn a natural-language feature requirement into a \
precise, testable contract for ONE Python function with JSON-compatible inputs and outputs.
Respond with ONLY a JSON object with exactly these keys:
{
  "function_name": "snake_case name (keep the name if the requirement gives one)",
  "parameters": [{"name": "...", "type": "Python type", "description": "..."}],
  "return_type": "Python type",
  "requirements": ["one atomic, testable behaviour per item", "..."],
  "assumptions": ["decisions you made that the requirement did not state"],
  "edge_cases": ["empty input, boundaries, invalid values, ordering, ties - where relevant"],
  "clarification_questions": [
    {"question": "only questions whose answer changes behaviour",
     "options": ["2-4 short, concrete, mutually exclusive choices"],
     "recommended": <index of the most conventional option>,
     "why": "one short line: what changes depending on the answer"}
  ]
}
Rules:
- 2 to 8 requirements. Each must be checkable by calling the function with concrete arguments.
- State behaviour for empty input, ordering, ties and invalid values when relevant to this task.
- Never invent business rules. If a behaviour-changing detail is missing, add a clarification question
  AND a provisional assumption (matching the recommended option).
- Ask as multiple choice: give 2-4 concrete options a busy developer can pick with one click
  (e.g. "Keep the first record seen", "Keep the most recently updated record"). At most 3 questions.
- Standard library only. No network, files, or user input."""

AUTO_RESOLVE = ("No human is available to answer questions: resolve every ambiguity yourself with the most "
                "conventional choice, record it under assumptions, and return an empty clarification_questions list.")

TEST_DESIGN_SYSTEM = """You are a meticulous QA engineer. From a confirmed function contract ONLY \
(you will never see the implementation), design declarative test cases.
Respond with ONLY a JSON object: {"test_cases": [ ... ]}, where each case is
{"requirement_ids": ["R1"], "description": "short", "args": [positional args], "kwargs": {},
 "expected": <exact JSON return value>}
or, when the contract says the call must fail,
{"requirement_ids": ["R2"], "description": "short", "args": [...], "kwargs": {}, "expected_exception": "ValueError"}
Rules:
- 6 to 12 cases. Every requirement id must be covered by at least one case.
- Include normal, boundary and invalid-input cases where the contract defines them.
- The expected value must follow strictly from the contract. Do not test behaviour the contract leaves open.
- Use only JSON values: tuples become lists, dict keys are strings, None is null, booleans are true/false.
- Use exactly one of "expected" or "expected_exception" per case.
- For floating-point results add "tolerance": 1e-9.
- When the contract requires a specific numeric type (e.g. "return an integer"), add "strict_type": true
  so 40 and 40.0 are distinguished."""

GENERATE_SYSTEM = """You are an expert Python 3.12 engineer. Implement the confirmed contract exactly.
Rules:
1. Define a function with exactly the contract's function_name and parameter order.
2. Standard library only. No I/O, no print, no input(), no network, no top-level side effects.
3. Type hints and a concise docstring. Raise the exceptions the contract specifies.
4. Inputs and outputs are JSON-compatible: return lists (not tuples or sets) and dicts with string keys
   unless the contract says otherwise.
5. Hidden test cases derived from the contract will check your code.
Respond in EXACTLY this format:

### EXPLANATION
<2-4 sentences>
### LIMITATIONS
<bullet list, or "- none">
### CODE
```python
<the complete implementation>
```"""

REPAIR_SYSTEM = GENERATE_SYSTEM + """

You are FIXING the implementation after real test failures. The contract and test cases are FROZEN:
you cannot change them and must not argue with them. Change only the code so that it satisfies the
contract and therefore the failing cases."""

CHALLENGE_SYSTEM = """You are an adversarial QA engineer trying to BREAK an implementation you cannot see.
From the confirmed contract only, propose NEW test cases most likely to expose bugs:
- inputs just below, at and just above every numeric threshold or limit in the contract
- every invalid input the contract defines behaviour for
- empty, single-element, duplicate, whitespace, mixed-case or unicode inputs where relevant
- combinations of flags/options
- at most 2 property cases, ONLY when the contract clearly implies the property:
  {"requirement_ids": [...], "description": "...", "args": [...], "kwargs": {}, "property": "idempotent"}
  (idempotent: f(f(x)) == f(x) applied to the first argument) or "property": "deterministic".
Every expected value must follow strictly from the contract; never test behaviour it leaves open.
Do not repeat inputs listed under "Already tested".
Respond with ONLY {"test_cases": [...]} using the same case format as before, at most 10 cases:
{"requirement_ids": ["R1"], "description": "short", "args": [...], "kwargs": {}, "expected": <JSON>}
or "expected_exception": "ValueError" instead of "expected". Use "strict_type": true where the contract
fixes the numeric type and "tolerance": 1e-9 for floats."""

REVISE_SYSTEM = """You update a confirmed function contract according to a change request.
Return ONLY the full revised contract JSON with the same keys as the original:
function_name, parameters, return_type, requirements, assumptions, edge_cases, clarification_questions.
"requirements" must be a list of objects {"source_id": "<id of the original requirement this keeps or
modifies, or null if new>", "text": "..."}.
Rules:
- Change ONLY what the change request implies. Copy every unaffected requirement's text VERBATIM with its source_id.
- A modified requirement keeps its source_id with new text. Requirements the change makes obsolete are omitted.
- Keep the function name and parameters unless the change explicitly alters them.
- Add a clarification question only if the change request is ambiguous in a way that changes behaviour,
  as multiple choice: {"question": "...", "options": ["2-4 concrete choices"], "recommended": <index>, "why": "..."}."""

REVISE_CODE_NOTE = """You are UPDATING an existing implementation to a revised contract. Keep all unchanged behaviour
exactly as it is; change only what the revised requirements require."""

DIRECT_SYSTEM = """Write a Python 3.12 function that satisfies the requirement. Standard library only.
Return only the code in one ```python block."""


def _examples_block(examples: list[dict]) -> str:
    if not examples:
        return "(none)"
    parts = []
    for ex in examples:
        code = ex["code"] if len(ex["code"]) < 1500 else ex["code"][:1500] + "\n# ..."
        parts.append(f"Requirement: {ex['requirement']}\n```python\n{code}\n```")
    return "\n\n".join(parts)


def _contract_for_prompt(contract: dict) -> str:
    """The user's original wording comes first and wins over the structured paraphrase.

    (Benchmark finding: small models' paraphrases sometimes drop or distort details, and a coder that only
    sees the paraphrase inherits those mistakes.)"""
    keys = ("function_name", "parameters", "return_type", "requirements", "assumptions", "edge_cases", "examples")
    body = json.dumps({k: contract.get(k) for k in keys}, indent=2)
    raw = (contract.get("raw_requirement") or "").strip()
    if not raw:
        return body
    return (f"Original requirement (authoritative; if the structured contract below conflicts with it, follow "
            f"this):\n{raw}\n\nStructured contract:\n{body}")


def analyze_messages(requirement: str, function_name: str | None = None, examples: list | None = None,
                     answers: list[dict] | None = None, auto_resolve: bool = False) -> list[dict]:
    user = f"Requirement:\n{requirement}"
    if function_name:
        user += f"\n\nThe function must be named `{function_name}`."
    if examples:
        user += "\n\nUser-supplied examples (treat as authoritative):\n" + json.dumps(examples, indent=2)
    if answers:
        qa = "\n".join(f"Q: {a['question']}\nA: {a['answer']}" for a in answers if a.get("answer"))
        user += ("\n\nThe user answered these clarification questions. Turn each answer into explicit "
                 f"requirements and do not ask them again:\n{qa}")
    if auto_resolve:
        user += "\n\n" + AUTO_RESOLVE
    return [{"role": "system", "content": ANALYZE_SYSTEM}, {"role": "user", "content": user}]


def _inputs_block(cases: list[dict]) -> str:
    return json.dumps([{"args": c["args"], "kwargs": c["kwargs"]} for c in cases])


def test_design_messages(contract: dict, only_ids: list[str] | None = None,
                         existing: list[dict] | None = None) -> list[dict]:
    user = f"Confirmed contract:\n{_contract_for_prompt(contract)}"
    if only_ids:
        user += (f"\n\nOnly design cases for these changed or new requirements: {', '.join(only_ids)}. "
                 "Every case must include at least one of them in requirement_ids.")
    if existing:
        user += f"\n\nAlready tested inputs (do not repeat): {_inputs_block(existing)}"
    return [{"role": "system", "content": TEST_DESIGN_SYSTEM}, {"role": "user", "content": user}]


def challenge_messages(contract: dict, existing: list[dict]) -> list[dict]:
    return [{"role": "system", "content": CHALLENGE_SYSTEM},
            {"role": "user", "content": f"Confirmed contract:\n{_contract_for_prompt(contract)}\n\n"
                                        f"Already tested: {_inputs_block(existing)}"}]


def revise_contract_messages(contract: dict, change: str) -> list[dict]:
    keys = ("function_name", "parameters", "return_type", "requirements", "assumptions", "edge_cases")
    return [{"role": "system", "content": REVISE_SYSTEM},
            {"role": "user", "content": f"Original contract:\n{json.dumps({k: contract[k] for k in keys}, indent=2)}"
                                        f"\n\nChange request:\n{change}"}]


def revise_code_messages(contract: dict, code: str, change: str, examples: list[dict]) -> list[dict]:
    msgs = generate_messages(contract, examples)
    msgs[0] = {"role": "system", "content": GENERATE_SYSTEM + "\n\n" + REVISE_CODE_NOTE}
    msgs[1]["content"] = (f"## Change request\n{change}\n\n## Current implementation\n```python\n{code}\n```\n\n"
                          + msgs[1]["content"])
    return msgs


def generate_messages(contract: dict, examples: list[dict]) -> list[dict]:
    user = (f"## Confirmed contract\n{_contract_for_prompt(contract)}\n\n"
            f"## Reference snippets from our verified team library (match their style; do not copy blindly)\n"
            f"{_examples_block(examples)}\n\nWrite the implementation.")
    return [{"role": "system", "content": GENERATE_SYSTEM}, {"role": "user", "content": user}]


def repair_messages(contract: dict, code: str, failures: str) -> list[dict]:
    user = (f"## Confirmed contract\n{_contract_for_prompt(contract)}\n\n"
            f"## Current implementation\n```python\n{code}\n```\n\n"
            f"## Observed failures (frozen test cases)\n{failures}\n\nReturn the corrected implementation.")
    return [{"role": "system", "content": REPAIR_SYSTEM}, {"role": "user", "content": user}]


def direct_messages(requirement: str, signature: str | None = None) -> list[dict]:
    user = requirement if not signature else f"{requirement}\n\nUse exactly this signature: {signature}"
    return [{"role": "system", "content": DIRECT_SYSTEM}, {"role": "user", "content": user}]


def schema_recovery_messages(original: list[dict], bad_output: str, error: str) -> list[dict]:
    return original + [{"role": "assistant", "content": bad_output[:4000]},
                       {"role": "user", "content": f"That response was invalid: {error}. "
                                                   "Reply again with ONLY the corrected JSON object."}]


# ---------- response parsing ----------

_FENCE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)


def _section(text: str, name: str) -> str | None:
    m = re.search(rf"#+\s*{name}\b(.*?)(?=\n#+\s*(?:EXPLANATION|LIMITATIONS|CODE)\b|\Z)", text, re.S | re.I)
    return m.group(1).strip() if m else None


def parse_generation(text: str) -> dict:
    """Extract explanation/limitations/code; tolerant of models that drift from the format."""
    code_sec = _section(text, "CODE") or ""
    m = _FENCE.search(code_sec) or _FENCE.search(text)
    code = m.group(1) if m else (code_sec or text)
    limitations = [l.lstrip("-* ").strip() for l in (_section(text, "LIMITATIONS") or "").splitlines()]
    limitations = [l for l in limitations if l and l.lower() not in ("none", "none.")]
    return {"explanation": _section(text, "EXPLANATION") or "", "limitations": limitations,
            "code": code.strip() + "\n"}


def parse_json(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        try:  # common SLM slip: trailing commas
            return json.loads(re.sub(r",\s*([}\]])", r"\1", m.group(0)))
        except json.JSONDecodeError:
            return None
