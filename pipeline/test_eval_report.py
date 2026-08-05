"""eval report 測試:runs.jsonl 分版聚合、markdown 產出、flaky 段。"""

import json

from pipeline.eval_report import aggregate_runs, main, render_report
from pipeline.flaky_gate import evaluate


def _runs_jsonl(tmp_path, name, rows):
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return path


def _row(case, attempt, outcome, ver="v1"):
    return {"ts": 0.0, "case_id": case, "template_version": ver,
            "attempt": attempt, "outcome": outcome}


def test_aggregate_groups_by_template_version(tmp_path):
    path = _runs_jsonl(tmp_path, "runs.jsonl", [
        _row("A", 1, "pass", "v1"),
        _row("B", 1, "schema", "v1"), _row("B", 2, "pass", "v1"),
        _row("A", 1, "pass", "v2"),
        _row("B", 1, "pass", "v2"),
    ])
    agg = aggregate_runs([path])
    assert len(agg["v1"]["first"]) == 2
    assert sum(1 for o in agg["v1"]["first"].values() if o == "pass") == 1
    assert agg["v1"]["by_class"] == {"schema": 1}
    assert sum(1 for o in agg["v2"]["first"].values() if o == "pass") == 2


def test_render_contains_rates_and_flaky(tmp_path):
    agg = aggregate_runs([_runs_jsonl(tmp_path, "r.jsonl", [
        _row("A", 1, "pass", "v1"), _row("B", 1, "sql_exec", "v1"),
    ])])
    gate = evaluate([{"A": "passed"}, {"A": "failed"}])
    report = render_report(agg, [("r1", {"A": "passed"}), ("r2", {"A": "failed"})], gate)
    assert "| v1 | 2 | 50% |" in report
    assert "FLAKY A: passed -> failed" in report


def test_main_writes_markdown(tmp_path, capsys):
    runs = _runs_jsonl(tmp_path, "runs.jsonl", [_row("A", 1, "pass")])
    out = tmp_path / "report.md"
    assert main(["--runs", str(runs), "--out", str(out)]) == 0
    assert out.exists()
    assert "# CaseSmith eval report" in out.read_text()
