import json
import unittest

from orchestrator.classify import Failure, FailureClass, PlannerBugError
from orchestrator.client import FakeClient
from orchestrator.core import GenerationFailed, Orchestrator, apply_patch

from pipeline.seed_planner import ModelSlot

SLOTS = [
    ModelSlot(table="T_Alpha", column="Note", type="nvarchar(200)",
              constraints="", reason="appears in WHERE",
              examples=("overdue follow-up", "priority customer")),
    ModelSlot(table="T_Beta", column="Code", type="char(4)",
              constraints="", reason="appears in JOIN",
              examples=("A001",)),
]

GOOD = json.dumps({"T_Alpha.Note": "overdue follow-up",
                   "T_Beta.Code": "A001"})


def orch(responses):
    return Orchestrator(FakeClient(responses))


class RunGenerateTest(unittest.TestCase):
    def test_first_attempt_pass(self):
        result = orch([GOOD]).run_generate("Case1", "ctx", SLOTS)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.values["T_Beta.Code"], "A001")
        self.assertEqual(result.template_version, "v1")

    def test_schema_failure_retries_with_strict_reminder(self):
        o = orch(["garbage", GOOD])
        result = o.run_generate("Case1", "ctx", SLOTS)
        self.assertEqual(result.attempts, 2)
        self.assertNotIn("STRICT FORMAT REMINDER", o.client.prompts[0])
        self.assertIn("STRICT FORMAT REMINDER", o.client.prompts[1])

    def test_schema_budget_exhausted_raises(self):
        o = orch(["garbage"] * 3)
        with self.assertRaises(GenerationFailed) as ctx:
            o.run_generate("Case1", "ctx", SLOTS)
        self.assertEqual(len(ctx.exception.attempts), 3)

    def test_sql_exec_raises_immediately_without_retry(self):
        client = FakeClient([GOOD, GOOD])
        o = Orchestrator(client)

        def validator(values):
            return [Failure(FailureClass.SQL_EXEC, "FK violation")]

        with self.assertRaises(PlannerBugError):
            o.run_generate("Case1", "ctx", SLOTS, validator=validator)
        self.assertEqual(len(client.prompts), 1)

    def test_semantic_retry_injects_fewshot_examples(self):
        calls = []

        def validator(values):
            calls.append(1)
            if len(calls) == 1:
                return [Failure(FailureClass.SEMANTIC, "implausible value")]
            return []

        o = orch([GOOD, GOOD])
        result = o.run_generate("Case1", "ctx", SLOTS, validator=validator)
        self.assertEqual(result.attempts, 2)
        self.assertNotIn("Known-good example values", o.client.prompts[0])
        self.assertIn("overdue follow-up | priority customer",
                      o.client.prompts[1])


class RunPatchTest(unittest.TestCase):
    def test_patch_pass(self):
        o = orch(['{"field": "T_Alpha.Note", "value": "fixed"}'])
        patch = o.run_patch("Case1", {"T_Alpha.Note": "old"},
                            "snapshot mismatch", {"T_Alpha.Note"})
        self.assertEqual(patch, {"field": "T_Alpha.Note", "value": "fixed"})

    def test_disallowed_field_exhausts_budget(self):
        bad = '{"field": "T_Zed.Bogus", "value": 1}'
        o = orch([bad] * 3)
        with self.assertRaises(GenerationFailed):
            o.run_patch("Case1", {"T_Alpha.Note": "old"}, "x",
                        {"T_Alpha.Note"})


class ApplyPatchTest(unittest.TestCase):
    def test_pure_replacement(self):
        artifact = {"a": 1, "b": 2}
        new = apply_patch(artifact, {"field": "a", "value": 9})
        self.assertEqual(new, {"a": 9, "b": 2})
        self.assertEqual(artifact, {"a": 1, "b": 2})

    def test_unknown_field_raises(self):
        with self.assertRaises(KeyError):
            apply_patch({"a": 1}, {"field": "zz", "value": 0})


if __name__ == "__main__":
    unittest.main()
