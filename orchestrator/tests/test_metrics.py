import tempfile
import unittest
from pathlib import Path

from orchestrator.metrics import MetricsLog


class MetricsTest(unittest.TestCase):
    def _log(self):
        return MetricsLog(Path(tempfile.mkdtemp()) / "runs.jsonl")

    def test_jsonl_one_line_per_record(self):
        log = self._log()
        log.record("Case1", "v1", 1, "pass")
        log.record("Case1", "v1", 2, "schema")
        lines = log.path.read_text().strip().splitlines()
        self.assertEqual(len(lines), 2)

    def test_summary_first_pass_rate_and_classes(self):
        log = self._log()
        log.record("Case1", "v1", 1, "pass")
        log.record("Case2", "v1", 1, "schema")
        log.record("Case2", "v1", 2, "pass")
        log.record("Case3", "v1", 1, "sql_exec")
        summary = log.summary()
        self.assertEqual(summary["total_cases"], 3)
        self.assertAlmostEqual(summary["first_pass_rate"], 1 / 3)
        self.assertEqual(summary["by_class"], {"schema": 1, "sql_exec": 1})

    def test_empty_log(self):
        summary = self._log().summary()
        self.assertEqual(summary["total_cases"], 0)
        self.assertEqual(summary["first_pass_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
