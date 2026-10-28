"""Scripted stand-in for a model, used by the offline tests and dev UI checks.

It is a SEEDED-FAULT FIXTURE: the first shipping_fee draft deliberately gets the 500
boundary wrong so the repair path can be tested without a live model. Never present
its output as real model generation.
"""
from __future__ import annotations

import json

SHIPPING_CONTRACT = {
    "function_name": "shipping_fee",
    "parameters": [{"name": "total", "type": "float", "description": "order total"},
                   {"name": "express", "type": "bool", "description": "express shipping"}],
    "return_type": "int | float",
    "requirements": ["Raise ValueError if total is negative.",
                     "Standard fee is 40 when total is below 500.",
                     "Standard fee is 0 when total is 500 or more.",
                     "Express adds 60 to the standard fee.",
                     "Return an integer for integer inputs."],
    "assumptions": ["total may be int or float"],
    "edge_cases": ["total == 499", "total == 500", "total < 0"],
    "clarification_questions": [],
}

SHIPPING_TESTS = {"test_cases": [
    {"requirement_ids": ["R2"], "description": "below threshold", "args": [499, False], "kwargs": {}, "expected": 40},
    {"requirement_ids": ["R3"], "description": "at threshold", "args": [500, False], "kwargs": {}, "expected": 0},
    {"requirement_ids": ["R4"], "description": "express below", "args": [100, True], "kwargs": {}, "expected": 100},
    {"requirement_ids": ["R3", "R4"], "description": "express at threshold", "args": [500, True], "kwargs": {}, "expected": 60},
    {"requirement_ids": ["R1"], "description": "negative", "args": [-1, False], "kwargs": {}, "expected_exception": "ValueError"},
    {"requirement_ids": ["R5"], "description": "int type", "args": [0, False], "kwargs": {}, "expected": 40, "strict_type": True},
    {"requirement_ids": ["R9"], "description": "bad id, must be rejected", "args": [1, False], "kwargs": {}, "expected": 40},
]}

BUGGY = '''### EXPLANATION
Computes the standard fee from the threshold and adds the express surcharge.
### LIMITATIONS
- none
### CODE
```python
def shipping_fee(total: float, express: bool) -> float:
    """Return the shipping fee for an order total."""
    if total < 0:
        raise ValueError("total cannot be negative")
    fee = 40 if total <= 500 else 0
    return fee + (60 if express else 0)
```'''

FIXED = BUGGY.replace("total <= 500", "total < 500")

AMBIGUOUS = {
    "function_name": "clean_customer_records",
    "parameters": [{"name": "records", "type": "list[dict]", "description": "customer records"}],
    "return_type": "list[dict]",
    "requirements": ["Strip whitespace from string fields.", "Remove duplicate customers."],
    "assumptions": ["Duplicates share the same email (provisional)."],
    "edge_cases": ["empty list"],
    "clarification_questions": [
        {"question": "Which field identifies a duplicate customer?",
         "options": ["Email (case-insensitive)", "Phone number", "Customer ID", "Name + email"],
         "recommended": 0, "why": "Decides which records count as the same customer."},
        {"question": "When duplicates exist, which record should be kept?",
         "options": ["The first one seen", "The most recently updated", "Merge their fields"],
         "recommended": 0, "why": "Changes which values survive deduplication."},
    ],
}


CHALLENGE = {"test_cases": [
    {"requirement_ids": ["R3"], "description": "exactly at threshold (float)", "args": [500.0, False], "kwargs": {}, "expected": 0},
    {"requirement_ids": ["R2"], "description": "just below", "args": [499.99, False], "kwargs": {}, "expected": 40},
    {"requirement_ids": ["R3", "R4"], "description": "above + express", "args": [501, True], "kwargs": {}, "expected": 60},
    {"requirement_ids": ["R2"], "description": "repeat of frozen T1", "args": [499, False], "kwargs": {}, "expected": 40},
    {"requirement_ids": ["R2"], "description": "deterministic", "args": [10, False], "kwargs": {}, "property": "deterministic"},
]}

REVISED_CONTRACT = dict(SHIPPING_CONTRACT, requirements=[
    {"source_id": "R1", "text": "Raise ValueError if total is negative."},
    {"source_id": "R2", "text": "Standard fee is 40 when total is below 750."},
    {"source_id": "R3", "text": "Standard fee is 0 when total is 750 or more."},
    {"source_id": "R4", "text": "Express adds 60 to the standard fee."},
    {"source_id": "R5", "text": "Return an integer for integer inputs."},
])

REVISED_TESTS = {"test_cases": [
    {"requirement_ids": ["R2"], "description": "below new threshold", "args": [749, False], "kwargs": {}, "expected": 40},
    {"requirement_ids": ["R3"], "description": "at new threshold", "args": [750, False], "kwargs": {}, "expected": 0},
    {"requirement_ids": ["R3", "R4"], "description": "express at new threshold", "args": [750, True], "kwargs": {}, "expected": 60},
    {"requirement_ids": ["R1"], "description": "targets unchanged req only", "args": [-5, False], "kwargs": {}, "expected_exception": "ValueError"},
]}

REVISED_CODE = FIXED.replace("total < 500", "total < 750")


class ScriptedClient:
    model = "scripted-fixture (seeded fault)"

    def __init__(self, *a, **k):
        self.usage = {}
        self.repairs = 0

    def chat(self, messages, **kw):
        system, user = messages[0]["content"], messages[-1]["content"]
        if system.startswith("You are a senior software analyst"):
            if "customer records" in user and "answered" not in user:
                return json.dumps(AMBIGUOUS)
            if "customer records" in user:
                c = dict(AMBIGUOUS, clarification_questions=[],
                         requirements=AMBIGUOUS["requirements"] + ["Duplicates are identified by lowercase email.",
                                                                   "Keep the first record seen."])
                return json.dumps(c)
            return "Sure! " + json.dumps(SHIPPING_CONTRACT)
        if system.startswith("You are an adversarial QA engineer"):
            return json.dumps(CHALLENGE)
        if system.startswith("You update a confirmed function contract"):
            return json.dumps(REVISED_CONTRACT)
        if system.startswith("You are a meticulous QA engineer"):
            return json.dumps(REVISED_TESTS if "Only design cases" in user else SHIPPING_TESTS)
        if "UPDATING" in system:
            return REVISED_CODE
        if "FIXING" in system:
            self.repairs += 1
            return FIXED
        return BUGGY
