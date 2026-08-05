"""Per-attempt JSONL log. Feeds the v1->vN improvement curve in the report."""

from __future__ import annotations

import json
import time
from pathlib import Path


class MetricsLog:
    def __init__(self, path):
        self.path = Path(path)

    def record(self, case_id: str, template_version: str, attempt: int,
               outcome: str) -> None:
        """outcome: "pass" or a FailureClass value."""
        row = {
            "ts": time.time(),
            "case_id": case_id,
            "template_version": template_version,
            "attempt": attempt,
            "outcome": outcome,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def summary(self) -> dict:
        rows = []
        if self.path.exists():
            with self.path.open(encoding="utf-8") as f:
                rows = [json.loads(line) for line in f if line.strip()]
        first_outcome: dict = {}
        by_class: dict = {}
        for row in rows:
            if row["attempt"] == 1 and row["case_id"] not in first_outcome:
                first_outcome[row["case_id"]] = row["outcome"]
            if row["outcome"] != "pass":
                by_class[row["outcome"]] = by_class.get(row["outcome"], 0) + 1
        total = len(first_outcome)
        passed = sum(1 for o in first_outcome.values() if o == "pass")
        return {
            "total_cases": total,
            "first_pass_rate": (passed / total) if total else 0.0,
            "by_class": by_class,
        }
