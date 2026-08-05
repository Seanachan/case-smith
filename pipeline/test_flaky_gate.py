"""flaky gate 判定器測試。result.json fixture 形狀對齊 result.v0.2 契約。"""

import json

import pytest

from pipeline.flaky_gate import evaluate, load_result, main


def _result_json(tmp_path, name, statuses):
    """statuses: {case_id: status} → 寫一份最小合規 result.json。"""
    path = tmp_path / name
    path.write_text(json.dumps({
        "test_results": [
            {"test_case_id": c, "status": s, "profile": "local_fake"}
            for c, s in statuses.items()
        ]
    }), encoding="utf-8")
    return path


def test_all_consistent_kept():
    runs = [{"A": "passed", "B": "failed"}] * 3
    report = evaluate(runs)
    assert report.stable == {"A": "passed", "B": "failed"}  # 一致 failed 也留
    assert report.clean


def test_inconsistent_kicked_as_flaky():
    runs = [{"A": "passed"}, {"A": "failed"}, {"A": "passed"}]
    report = evaluate(runs)
    assert report.flaky == {"A": ["passed", "failed", "passed"]}
    assert "A" not in report.kept
    assert not report.clean


def test_blocked_is_undetermined_not_flaky():
    runs = [{"A": "passed"}, {"A": "blocked"}, {"A": "passed"}]
    report = evaluate(runs)
    assert "A" in report.undetermined
    assert "A" not in report.flaky


def test_case_missing_from_one_run():
    runs = [{"A": "passed", "B": "passed"}, {"A": "passed"}, {"A": "passed", "B": "passed"}]
    report = evaluate(runs)
    assert report.missing == {"B": 2}
    assert report.stable == {"A": "passed"}


def test_fewer_than_two_runs_rejected():
    with pytest.raises(ValueError):
        evaluate([{"A": "passed"}])


def test_load_result_reads_test_results_not_top_level(tmp_path):
    path = _result_json(tmp_path, "r.json", {"A": "failed"})
    assert load_result(path) == {"A": "failed"}


def test_load_result_empty_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"status": "passed"}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_result(path)


def test_cli_exit_codes(tmp_path, capsys):
    ok = [_result_json(tmp_path, f"ok{i}.json", {"A": "passed"}) for i in range(3)]
    assert main([str(p) for p in ok]) == 0
    flaky = [
        _result_json(tmp_path, "f1.json", {"A": "passed"}),
        _result_json(tmp_path, "f2.json", {"A": "failed"}),
    ]
    assert main([str(p) for p in flaky]) == 1
    assert "FLAKY" in capsys.readouterr().out
