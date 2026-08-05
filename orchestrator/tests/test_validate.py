import unittest

from pipeline.seed_planner import ModelSlot
from orchestrator.validate import SchemaError, parse_flat_json, validate_patch


def slots(*names):
    return [ModelSlot(table=n.split(".")[0], column=n.split(".")[1],
                      type="nvarchar(50)", constraints="",
                      reason="appears in WHERE")
            for n in names]


class ParseFlatJsonTest(unittest.TestCase):
    def test_extracts_json_surrounded_by_chatter(self):
        raw = 'Sure! Here you go:\n{"T_Alpha.Note": "hi"}\nHope that helps.'
        self.assertEqual(parse_flat_json(raw, slots("T_Alpha.Note")),
                         {"T_Alpha.Note": "hi"})

    def test_brace_inside_string_value_ok(self):
        raw = '{"T_Alpha.Note": "curly } inside"}'
        self.assertEqual(parse_flat_json(raw, slots("T_Alpha.Note")),
                         {"T_Alpha.Note": "curly } inside"})

    def test_missing_key_rejected(self):
        with self.assertRaises(SchemaError):
            parse_flat_json('{"T_Alpha.Note": "x"}',
                            slots("T_Alpha.Note", "T_Beta.Code"))

    def test_extra_key_rejected(self):
        with self.assertRaises(SchemaError):
            parse_flat_json('{"T_Alpha.Note": "x", "T_Zed.Bogus": 1}',
                            slots("T_Alpha.Note"))

    def test_nested_value_rejected(self):
        with self.assertRaises(SchemaError):
            parse_flat_json('{"T_Alpha.Note": {"deep": 1}}',
                            slots("T_Alpha.Note"))

    def test_no_json_rejected(self):
        with self.assertRaises(SchemaError):
            parse_flat_json("no json here", slots("T_Alpha.Note"))


class ValidatePatchTest(unittest.TestCase):
    def test_valid_patch(self):
        raw = '{"field": "T_Alpha.Note", "value": "fixed"}'
        self.assertEqual(validate_patch(raw, {"T_Alpha.Note"}),
                         {"field": "T_Alpha.Note", "value": "fixed"})

    def test_wrong_key_set_rejected(self):
        with self.assertRaises(SchemaError):
            validate_patch('{"field": "T_Alpha.Note"}', {"T_Alpha.Note"})

    def test_field_outside_allowlist_rejected(self):
        with self.assertRaises(SchemaError):
            validate_patch('{"field": "T_Zed.Bogus", "value": 1}',
                           {"T_Alpha.Note"})


if __name__ == "__main__":
    unittest.main()
