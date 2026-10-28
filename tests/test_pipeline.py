"""Deterministic tests (mocked model, no API keys). Run: python -m unittest discover tests"""
from __future__ import annotations

import io
import json
import sys
import unittest
import zipfile
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent.parent), str(Path(__file__).resolve().parent)]

from fake_llm import BUGGY, FIXED, SHIPPING_CONTRACT, ScriptedClient  # noqa: E402
from snipforge import evolve, pipeline, prompts, reporting  # noqa: E402
from snipforge.mutation import generate_mutants, mutation_test  # noqa: E402
from snipforge.contracts import (ContractError, normalize_contract, requirement_evidence,  # noqa: E402
                                 validate_cases)
from snipforge.retriever import Retriever  # noqa: E402
from snipforge.runner import execute_cases, run_once, values_equal  # noqa: E402
from snipforge.validator import check_syntax, policy_check, static_analysis  # noqa: E402

CONTRACT = normalize_contract(SHIPPING_CONTRACT, "shipping fee")


def case(id, args, **exp):
    return {"id": id, "requirement_ids": ["R1"], "args": args, "kwargs": {}, **exp}


def run(contract=CONTRACT, client=None, **kw):
    client = client or ScriptedClient()
    events = list(pipeline.run_generation(contract, "ollama", client=client, **kw))
    return events, events[-1]


class TestContracts(unittest.TestCase):
    def test_numbering_and_rejects_bad_name(self):
        self.assertEqual([r["id"] for r in CONTRACT["requirements"]], ["R1", "R2", "R3", "R4", "R5"])
        with self.assertRaises(ContractError):
            normalize_contract({**SHIPPING_CONTRACT, "function_name": "bad name"}, "x")
        with self.assertRaises(ContractError):
            normalize_contract({**SHIPPING_CONTRACT, "requirements": []}, "x")

    def test_case_validation(self):
        cases, errors = validate_cases([
            {"requirement_ids": ["R1"], "args": [1, True], "expected": 1},
            {"requirement_ids": ["R1"], "args": [1], "expected": 1, "expected_exception": "ValueError"},
            {"requirement_ids": ["R1"], "args": [1]},
            {"requirement_ids": ["R99"], "args": [1], "expected": 1},
            {"requirement_ids": ["R1"], "args": "1", "expected": 1},
            {"requirement_ids": ["R1"], "args": [1], "expected_exception": "os.system('x')"},
            {"requirement_ids": ["R1"], "args": [1], "expected": None},
        ], CONTRACT)
        self.assertEqual(len(cases), 2)  # first and last (expected null is a real expectation)
        self.assertEqual(len(errors), 5)
        self.assertIn("expected", cases[1])

    def test_evidence_marks_untested(self):
        cases = [{"id": "T1", "requirement_ids": ["R1"]}]
        ev = requirement_evidence(CONTRACT, cases, [{"test_id": "T1", "status": "pass"}])
        self.assertEqual(ev[0]["outcome"], "passed")
        self.assertTrue(all(e["outcome"] == "not tested" for e in ev[1:]))
        self.assertEqual(requirement_evidence(CONTRACT, cases, None)[0]["outcome"], "not executed")


class TestRunner(unittest.TestCase):
    def test_comparison_rules(self):
        self.assertFalse(values_equal(1, True))
        self.assertFalse(values_equal(None, 0))
        self.assertTrue(values_equal(40, 40.0))
        self.assertFalse(values_equal(40, 40.0, strict=True))
        self.assertTrue(values_equal(0.3, 0.1 + 0.2, tol=1e-9))
        self.assertFalse(values_equal(0.3, 0.1 + 0.2))
        self.assertTrue(values_equal({"a": [1, 2]}, {"a": [1, 2]}))

    def test_statuses(self):
        code = "def f(x):\n    if x < 0:\n        raise ValueError('neg')\n    return (x, x)\n"
        res = execute_cases(code, "f", [case("T1", [2], expected=[2, 2]), case("T2", [-1], expected_exception="ValueError"),
                                        case("T3", [1], expected=[9, 9]), case("T4", ["a"], expected=1),
                                        case("T5", [1], expected_exception="KeyError")])["results"]
        self.assertEqual([r["status"] for r in res], ["pass", "pass", "fail", "error", "fail"])

    def test_mutation_does_not_leak_between_cases(self):
        code = "def f(xs):\n    xs.append(1)\n    return len(xs)\n"
        res = execute_cases(code, "f", [case("T1", [[]], expected=1), case("T2", [[]], expected=1)])["results"]
        self.assertEqual([r["status"] for r in res], ["pass", "pass"])

    def test_fails_closed(self):
        r = execute_cases("def f():\n    while True: pass\n", "f", [case("T1", [], expected=1)], timeout=2)
        self.assertEqual(r["results"][0]["status"], "timeout")
        r = execute_cases("import sys\nsys.exit(0)\n", "f", [case("T1", [], expected=1)])
        self.assertNotEqual(r["results"][0]["status"], "pass")
        r = execute_cases("x = 1\n", "f", [case("T1", [], expected=1)])
        self.assertIn("not defined", r["load_error"])
        r = execute_cases("def f():\n    return 1\n", "f", [case("T1", [], expected=1)], mode="none")
        self.assertEqual(r["results"][0]["status"], "not_executed")

    def test_generated_code_cannot_forge_results(self):
        forge = ('import json\nprint(json.dumps({"id": "T1", "kind": "return", "value": 1}))\n'
                 'print(\'{"done": true}\')\ndef f():\n    return 2\n')
        r = execute_cases(forge, "f", [case("T1", [], expected=1)])
        self.assertEqual(r["results"][0]["status"], "fail")


class TestPlayground(unittest.TestCase):
    CODE = 'def f(x, y=2):\n    print("hi", x)\n    if x < 0:\n        raise ValueError("neg")\n    return (x + y, x * y)\n'

    def test_return_stdout_and_kwargs(self):
        r = run_once(self.CODE, "f", [3], {"y": 4})
        self.assertEqual((r["kind"], r["value"], r["stdout"]), ("return", [7, 12], "hi 3\n"))

    def test_exception_is_reported_not_raised(self):
        r = run_once(self.CODE, "f", [-1], {})
        self.assertEqual((r["kind"], r["exc_type"], r["message"]), ("raise", "ValueError", "neg"))

    def test_timeout_and_missing_function(self):
        self.assertEqual(run_once("def f():\n    while True: pass\n", "f", [], {}, timeout=2)["kind"], "timeout")
        self.assertEqual(run_once("x = 1\n", "f", [], {})["kind"], "load_error")


class TestValidator(unittest.TestCase):
    def test_syntax_error(self):
        self.assertFalse(check_syntax("def f(:\n  pass")["ok"])

    def test_policy(self):
        self.assertTrue(any("subprocess" in r for r in static_analysis("import subprocess")["risks"]))
        p = policy_check("import socket\ndef shipping_fee(total, express):\n    return 1\n", CONTRACT)
        self.assertEqual(p["status"], "fail")
        p = policy_check("def other():\n    return 1\n", CONTRACT)
        self.assertIn("not defined", p["blocked"][0])
        p = policy_check("def shipping_fee(express, total):\n    return 1\n", CONTRACT)
        self.assertEqual(p["status"], "warn")


class TestParsing(unittest.TestCase):
    def test_parse_generation(self):
        g = prompts.parse_generation(BUGGY)
        self.assertIn("def shipping_fee", g["code"])
        self.assertTrue(g["explanation"])
        self.assertEqual(g["limitations"], [])

    def test_parse_json_trailing_comma(self):
        self.assertEqual(prompts.parse_json('Sure! {"a": [1, 2,],}'), {"a": [1, 2]})


class TestRetrieval(unittest.TestCase):
    def test_finds_relevant(self):
        self.assertEqual(Retriever().search("check if an email address is valid", k=2)[0]["id"], "validate-email")


class TestPipeline(unittest.TestCase):
    def test_analyze_and_clarification(self):
        a = pipeline.analyze("Clean customer records and remove duplicates.", "ollama", client=ScriptedClient())
        self.assertEqual(a["state"], "needs_clarification")
        a2 = pipeline.analyze("Clean customer records and remove duplicates.", "ollama", client=ScriptedClient(),
                              answers=[{"question": "Which field?", "answer": "email"}])
        self.assertEqual(a2["state"], "contract_ready")
        a3 = pipeline.analyze("Clean customer records", "ollama", client=ScriptedClient(), auto_resolve=True)
        self.assertEqual(a3["state"], "contract_ready")

    def test_repair_is_code_only_and_tests_frozen(self):
        events, res = run()
        tests_ev = next(e for e in events if e.get("stage") == "tests" and e["status"] == "done")
        self.assertEqual(res["status"], "passed")
        self.assertTrue(res["repair_attempted"] and res["tests_unchanged"])
        self.assertEqual(res["test_cases"], tests_ev["data"]["test_cases"])
        self.assertEqual(res["hashes"]["test_set"], tests_ev["data"]["test_set_hash"])
        self.assertEqual(res["attempts"][0]["status"], "failed")
        self.assertEqual(len(res["rejected_cases"]), 1)
        self.assertIn("-    fee = 40 if total <= 500", res["diff"])
        self.assertEqual(res["model_calls"], 5)  # tests + generate + 2 consensus candidates + 1 repair

    def test_generation_prompt_never_contains_tests(self):
        client = ScriptedClient()
        seen = []
        orig = client.chat
        client.chat = lambda m, **k: (seen.append(m), orig(m, **k))[1]
        run(client=client)
        gen_prompt = next(m for m in seen if m[0]["content"].startswith("You are an expert"))
        for marker in ("express at threshold", "expected_exception", "test_cases"):  # only exist in the tests
            self.assertNotIn(marker, gen_prompt[1]["content"])

    def test_no_repair_budget_reports_failure(self):
        _, res = run(max_repairs=0)
        self.assertEqual(res["status"], "failed")
        self.assertFalse(res["repair_attempted"])
        self.assertTrue(any(e["outcome"] == "failed" for e in res["evidence"]))

    def test_unavailable_runner_is_not_a_pass(self):
        orig = pipeline.execution_mode
        pipeline.execution_mode = lambda: "none"
        try:
            _, res = run()
        finally:
            pipeline.execution_mode = orig
        self.assertEqual(res["status"], "not_executed")
        self.assertTrue(all(e["outcome"] in ("not executed", "not tested") for e in res["evidence"]))

    def test_export_bundle(self):
        _, res = run()
        z = zipfile.ZipFile(io.BytesIO(reporting.bundle(res)))
        self.assertEqual(sorted(z.namelist()),
                         ["contract.json", "report.md", "solution.py", "test_cases.json", "test_solution.py"])
        self.assertEqual(json.loads(z.read("contract.json"))["function_name"], "shipping_fee")
        compile(z.read("test_solution.py"), "test_solution.py", "exec")


class TestNamedFunction(unittest.TestCase):
    def test_explicit_name_is_binding(self):
        self.assertEqual(pipeline.explicit_function_name("Implement shipping_fee(total, express). Reject"), "shipping_fee")
        self.assertIsNone(pipeline.explicit_function_name("status is active (case-insensitive)"))

    def test_invented_parameters_are_dropped(self):
        class Inventive(ScriptedClient):
            def chat(self, messages, **kw):
                if messages[0]["content"].startswith("You are a senior software analyst"):
                    extra = dict(SHIPPING_CONTRACT, parameters=SHIPPING_CONTRACT["parameters"] +
                                 [{"name": "currency", "type": "str"}])
                    return json.dumps(extra)
                return super().chat(messages, **kw)
        a = pipeline.analyze("Implement shipping_fee(total, express). Free at 500.", "ollama", client=Inventive())
        self.assertEqual([p["name"] for p in a["contract"]["parameters"]], ["total", "express"])
        self.assertTrue(any("currency" in x for x in a["contract"]["assumptions"]))

    def test_fallback_contract_when_json_is_unusable(self):
        class Garbled(ScriptedClient):
            def chat(self, messages, **kw):
                return '{"name: total", broken' if messages[0]["content"].startswith("You are a senior") else \
                    super().chat(messages, **kw)
        a = pipeline.analyze("Implement shipping_fee(total, express). Reject negative totals with ValueError. "
                             "Express adds 60.", "ollama", client=Garbled())
        self.assertEqual([r["text"] for r in a["contract"]["requirements"]],
                         ["Reject negative totals with ValueError.", "Express adds 60."])
        self.assertIn("unusable", a["contract"]["assumptions"][0])
        with self.assertRaises(pipeline.PipelineError):  # no name to fall back on
            pipeline.analyze("Clean the records.", "ollama", client=Garbled())

    def test_best_attempt_is_reported(self):
        """A repair that makes things worse must not replace better code."""
        class WorseRepair(ScriptedClient):
            def chat(self, messages, **kw):
                if "FIXING" in messages[0]["content"]:
                    return "### CODE\n```python\ndef shipping_fee(total, express):\n    return (\n```"
                return super().chat(messages, **kw)
        _, res = run(client=WorseRepair())
        self.assertEqual(res["selected_attempt"], 1)
        self.assertEqual(len(res["attempts"]), 2)
        self.assertTrue(check_syntax(res["code"])["ok"])


class TestConsensus(unittest.TestCase):
    A = "def f(x):\n    return x * 2\n"
    B = "def f(x):\n    y = x + x\n    return y\n"
    C = "def f(x):\n    return x * 3\n"
    CT = normalize_contract({"function_name": "f", "parameters": [{"name": "x"}], "requirements": ["double x"]}, "double")

    def _cases(self):
        return [case("T1", [2], expected=4), case("T2", [3], expected=7)]  # T2's expectation is wrong

    def test_wrong_test_is_disputed_not_deleted(self):
        cs = self._cases()
        va = pipeline._verify(self.A, self.CT, cs, "process")
        vb = pipeline._verify(self.B, self.CT, cs, "process")
        disputed = pipeline.find_disputes(self.A, va, self.B, vb)
        self.assertEqual(disputed, {"T2"})
        v = pipeline._verify(self.A, self.CT, cs, "process", disputed)
        self.assertEqual(v["status"], "passed")
        self.assertEqual(v["counts"]["disputed"], 1)
        self.assertEqual([r["status"] for r in v["results"]], ["pass", "disputed"])
        ev = requirement_evidence(self.CT, cs, v["results"])
        self.assertEqual(ev[0]["outcome"], "disputed")

    def test_agreement_outvotes_wrong_tests(self):
        """Weak tests expect x*3; one candidate matches them, two different correct ones agree on x*2."""
        cs = [case("T1", [2], expected=6), case("T2", [3], expected=9), case("T3", [0], expected=0)]
        cands = [{"source": "contract", "code": self.C}, {"source": "direct", "code": self.A},
                 {"source": "direct-2", "code": self.B}]
        for cd in cands:
            cd["v"] = pipeline._verify(cd["code"], self.CT, cs, "process")
        sel = pipeline.select_by_agreement(cands)  # same-model tests: agreement wins
        self.assertIn(cands[sel["chosen"]]["source"], ("direct", "direct-2"))
        self.assertEqual(sel["disputed"], {"T1", "T2"})
        self.assertEqual(sel["winning_group_size"], 2)
        trusted = pipeline.select_by_agreement(cands, trust_tests=True)  # independent tests: 1x3 passes > 2x1
        self.assertEqual(cands[trusted["chosen"]]["source"], "contract")

    def test_strong_tests_beat_a_lone_majority_of_identical_code(self):
        """Identical code counts once: two copies of a wrong answer are not two votes."""
        cs = [case("T1", [2], expected=4), case("T2", [3], expected=6)]
        cands = [{"source": "contract", "code": self.A}, {"source": "direct", "code": self.C},
                 {"source": "direct-2", "code": self.C + "\n"}]
        for cd in cands:
            cd["v"] = pipeline._verify(cd["code"], self.CT, cs, "process")
        sel = pipeline.select_by_agreement(cands, trust_tests=True)
        self.assertEqual(cands[sel["chosen"]]["source"], "contract")
        self.assertEqual(sel["disputed"], frozenset())
        # Untrusted (same small model) tests may not override the plain-prompt default.
        self.assertEqual(cands[pipeline.select_by_agreement(cands)["chosen"]]["source"], "direct")

    def test_disagreeing_implementations_do_not_dispute(self):
        cs = self._cases()
        va = pipeline._verify(self.A, self.CT, cs, "process")
        vc = pipeline._verify(self.C, self.CT, cs, "process")
        self.assertEqual(pipeline.find_disputes(self.A, va, self.C, vc), frozenset())

    def test_identical_code_gives_no_signal(self):
        cs = self._cases()
        va = pipeline._verify(self.A, self.CT, cs, "process")
        self.assertEqual(pipeline.find_disputes(self.A, va, self.A + "\n", va), frozenset())

    def test_better_independent_candidate_is_selected(self):
        class DirectIsRight(ScriptedClient):
            def chat(self, messages, **kw):
                if messages[0]["content"].startswith("Write a Python 3.12 function"):
                    return FIXED
                return super().chat(messages, **kw)
        res = list(pipeline.run_generation(CONTRACT, "ollama", client=DirectIsRight()))[-1]
        self.assertEqual(res["consensus"]["selected"], "direct")
        self.assertEqual(res["status"], "passed")
        self.assertFalse(res["repair_attempted"])  # no repair needed: the better candidate already passes


class TestTrustPolicy(unittest.TestCase):
    def test_small_model_mode_disables_repair(self):
        res = list(pipeline.run_generation(CONTRACT, "ollama", client=ScriptedClient(), trust_own_tests=False))[-1]
        self.assertFalse(res["repair_attempted"])
        self.assertFalse(res["test_designer"]["tests_trusted"])
        self.assertEqual(res["status"], "failed")  # the seeded bug is reported, not hidden

    def test_independent_designer_is_always_trusted(self):
        tester = ScriptedClient()
        tester.model = "independent-tester"
        res = list(pipeline.run_generation(CONTRACT, "ollama", client=ScriptedClient(), tests_client=tester,
                                           trust_own_tests=False))[-1]
        self.assertTrue(res["test_designer"]["tests_trusted"])
        self.assertTrue(res["repair_attempted"])


class TestIndependentTestDesigner(unittest.TestCase):
    def test_tests_and_code_come_from_different_clients(self):
        coder, tester = ScriptedClient(), ScriptedClient()
        tester.model = "independent-tester"
        log = {"coder": [], "tester": []}
        for name, cl in (("coder", coder), ("tester", tester)):
            orig = cl.chat
            cl.chat = (lambda o, n: lambda m, **k: (log[n].append(m[0]["content"][:30]), o(m, **k))[1])(orig, name)
        res = list(pipeline.run_generation(CONTRACT, "ollama", client=coder, tests_client=tester))[-1]
        self.assertEqual(res["status"], "passed")
        self.assertTrue(all(x.startswith("You are a meticulous QA") for x in log["tester"]))
        self.assertFalse(any(x.startswith("You are a meticulous QA") for x in log["coder"]))
        self.assertEqual(len(log["tester"]), 1)
        self.assertEqual(res["test_designer"]["model"], "independent-tester")
        self.assertTrue(res["test_designer"]["independent"])

    def test_same_model_is_reported_as_not_independent(self):
        res = run()[1]
        self.assertFalse(res["test_designer"]["independent"])


class TestProperties(unittest.TestCase):
    def test_property_cases(self):
        cases, errors = validate_cases([{"requirement_ids": ["R1"], "args": [[1]], "property": "idempotent"},
                                        {"requirement_ids": ["R1"], "args": [[1]], "property": "commutative"},
                                        {"requirement_ids": ["R1"], "args": [[2]], "property": "idempotent",
                                         "expected": 1}], CONTRACT)
        self.assertEqual(len(cases), 1)
        self.assertEqual(len(errors), 2)
        good = "def f(xs):\n    return sorted(set(xs))\n"
        bad = "def f(xs):\n    return xs + [0]\n"
        c = [{**cases[0], "args": [[3, 1, 3]]}]
        self.assertEqual(execute_cases(good, "f", c)["results"][0]["status"], "pass")
        self.assertEqual(execute_cases(bad, "f", c)["results"][0]["status"], "fail")


class TestChallengeAndRevision(unittest.TestCase):
    def _buggy(self):
        return run(max_repairs=0)[1]

    def test_challenge_finds_boundary_and_skips_known_inputs(self):
        ch = evolve.challenge(self._buggy(), "ollama", client=ScriptedClient())
        self.assertEqual([f["case"]["args"] for f in ch["findings"]], [[500.0, False]])
        self.assertEqual(ch["findings"][0]["requirements"][0]["id"], "R3")
        self.assertTrue(any("already covered" in r for r in ch["rejected"]))
        self.assertEqual(ch["model_calls"], 1)

    def test_regression_capture_creates_new_version(self):
        parent = self._buggy()
        parent["challenge"] = evolve.challenge(parent, "ollama", client=ScriptedClient())
        res = list(evolve.regress(parent, "p1", ["C1"], "ollama", client=ScriptedClient()))[-1]
        self.assertEqual((res["version"], res["parent_run_id"], res["status"]), (2, "p1", "passed"))
        self.assertEqual(res["test_changes"]["added"], ["T7"])
        self.assertEqual(res["test_cases"][-1]["origin"], "challenge C1")
        self.assertTrue(res["repair_attempted"])

    def test_revision_keeps_unaffected_tests(self):
        good = run()[1]
        prop = evolve.propose_revision(good, "make free shipping start at 750", "ollama", client=ScriptedClient())
        self.assertEqual([d["status"] for d in prop["requirement_diff"]],
                         ["unchanged", "modified", "modified", "unchanged", "unchanged"])
        res = list(evolve.run_revision(good, "g1", prop["contract"], prop["change"], "ollama",
                                       client=ScriptedClient()))[-1]
        self.assertEqual(res["status"], "passed")
        self.assertEqual(res["test_changes"]["kept"], ["T3", "T5", "T6"])  # only tests on unchanged requirements
        self.assertEqual(res["regression"], {"total": 3, "pass": 3})
        self.assertNotIn("T1", [t["id"] for t in res["test_cases"]])
        self.assertIn("+    fee = 40 if total < 750", res["version_diff"])
        self.assertEqual(res["version"], 2)


class TestMutation(unittest.TestCase):
    CODE = ('def shipping_fee(total, express):\n    """Fee."""\n    if total < 0:\n        raise ValueError("neg")\n'
            '    fee = 40 if total < 500 else 0\n    return fee + (60 if express else 0)\n')

    def test_deterministic_and_bounded(self):
        a, b = generate_mutants(self.CODE), generate_mutants(self.CODE)
        self.assertEqual([m["code"] for m in a], [m["code"] for m in b])
        self.assertLessEqual(len(a), 5)
        self.assertEqual(a[0]["before"], "fee = 40 if total < 500 else 0")  # business threshold first

    def test_weak_tests_let_threshold_mutant_survive(self):
        weak = [case("T1", [499, False], expected=40), case("T2", [-1, False], expected_exception="ValueError")]
        run_ = {"status": "passed", "code": self.CODE, "contract": CONTRACT, "test_cases": weak,
                "hashes": {"test_set": "x"}}
        out = {m["description"] + m["before"]: m["outcome"] for m in mutation_test(run_)["mutants"]}
        self.assertEqual(out["`<` → `<=`fee = 40 if total < 500 else 0"], "survived")
        strong = weak + [case("T3", [500, False], expected=0), case("T4", [10, True], expected=100),
                         case("T5", [0, False], expected=40)]  # without T5 the `< 0` -> `<= 0` mutant survives
        res = mutation_test({**run_, "test_cases": strong})
        self.assertEqual(res["summary"]["survived"], 0)

    def test_refuses_failing_code(self):
        with self.assertRaises(ValueError):
            mutation_test({"status": "failed"})


if __name__ == "__main__":
    unittest.main()
