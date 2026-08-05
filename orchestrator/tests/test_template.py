import tempfile
import unittest
from pathlib import Path

from orchestrator.template import load_template, render


class TemplateTest(unittest.TestCase):
    def _write(self, text):
        path = Path(tempfile.mkdtemp()) / "t.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_version_parsed(self):
        t = load_template(self._write("<!-- version: v3 -->\nhi {{x}}"))
        self.assertEqual(t.version, "v3")

    def test_missing_version_raises(self):
        with self.assertRaises(ValueError):
            load_template(self._write("no version header\n"))

    def test_render_replaces_all_placeholders(self):
        t = load_template(self._write("<!-- version: v1 -->\n{{a}}-{{b}}"))
        self.assertIn("1-2", render(t, {"a": "1", "b": "2"}))

    def test_missing_placeholder_value_raises(self):
        t = load_template(self._write("<!-- version: v1 -->\n{{a}}-{{b}}"))
        with self.assertRaises(KeyError):
            render(t, {"a": "1"})


if __name__ == "__main__":
    unittest.main()
