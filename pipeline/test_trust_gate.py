"""trust_gate 單元測試:假 suite_manifest / 假 result JSON,不碰真框架執行。

result JSON 形狀依 docs/ARTF_CONTRACT.md Q7:test_results[] 每筆
{test_case_id, status, profile, ...},status ∈ passed|failed|blocked。
"""

import json

import pytest

from pipeline.trust_gate import TrustGateReport, compare_runs, shuffle_manifests

MANIFEST = {
    "contract_version": "v0.2",
    "suite_id": "CASESMITH-TRUSTGATE-DEMO",
    "profile": "local_fake",
    "selection": {"mode": "suite", "suite": "CASESMITH-TRUSTGATE-DEMO"},
    "tests": [
        "test_cases/Characterize_A.yaml",
        "test_cases/Characterize_B.yaml",
        "test_cases/Characterize_C.yaml",
        "test_cases/Characterize_D.yaml",
    ],
    "artifact_roots": {
        "provider_instances": "provider_instances/",
        "env_profiles": "env_profiles/",
    },
}


def _entries(statuses: dict) -> list:
    return [
        {"test_case_id": f"Characterize_{name}", "status": status, "profile": "local_fake"}
        for name, status in statuses.items()
    ]


def _result(test_results: list, run_id: str = "RUN-1") -> dict:
    """最小可用的 ARTF result JSON(Q7 required_fields 都填,compare_runs 只讀 test_results)。"""
    return {
        "framework_version": "0.2.7",
        "dsl_version": "v0.2",
        "suite_id": "CASESMITH-TRUSTGATE-DEMO",
        "batch_id": "BATCH-1",
        "run_id": run_id,
        "test_case_id": None,
        "test_count": len(test_results),
        "status": "passed" if all(t["status"] == "passed" for t in test_results) else "failed",
        "profile": "local_fake",
        "environment": "local",
        "start_time": "2026-08-05T00:00:00Z",
        "end_time": "2026-08-05T00:00:01Z",
        "duration_ms": 1000,
        "timestamps": {"created_at": "2026-08-05T00:00:00Z"},
        "test_results": test_results,
        "provider_results": [],
        "steps": [],
        "verify_results": [],
        "evidence_refs": [],
        "failure": None,
    }


# ---------------------------------------------------------------------------
# compare_runs
# ---------------------------------------------------------------------------


def test_all_stable_when_three_runs_agree():
    base = {"A": "passed", "B": "passed", "C": "failed", "D": "blocked"}
    results = [_result(_entries(base), run_id=f"RUN-{i}") for i in range(3)]
    report = compare_runs(results)
    assert report.stable == {
        "Characterize_A": "passed",
        "Characterize_B": "passed",
        "Characterize_C": "failed",
        "Characterize_D": "blocked",
    }
    assert report.kicked == {}


def test_third_run_flips_one_case_to_kicked():
    run0 = {"A": "passed", "B": "passed", "C": "failed", "D": "blocked"}
    run1 = dict(run0)
    run2 = dict(run0)
    run2["B"] = "failed"  # 第三次翻紅
    results = [
        _result(_entries(run0), run_id="RUN-0"),
        _result(_entries(run1), run_id="RUN-1"),
        _result(_entries(run2), run_id="RUN-2"),
    ]
    report = compare_runs(results)
    assert report.kicked == {"Characterize_B": ["passed", "passed", "failed"]}
    assert report.stable == {
        "Characterize_A": "passed",
        "Characterize_C": "failed",
        "Characterize_D": "blocked",
    }


def test_case_set_mismatch_raises():
    full = {"A": "passed", "B": "passed", "C": "failed", "D": "blocked"}
    missing_one = {k: v for k, v in full.items() if k != "C"}
    results = [
        _result(_entries(full), run_id="RUN-0"),
        _result(_entries(missing_one), run_id="RUN-1"),
        _result(_entries(full), run_id="RUN-2"),
    ]
    with pytest.raises(ValueError, match="case 集合"):
        compare_runs(results)


def test_missing_test_case_id_raises():
    entries = [{"status": "passed", "profile": "local_fake"}]
    with pytest.raises(ValueError, match="test_case_id"):
        compare_runs([_result(entries)])


def test_compare_runs_empty_list_raises():
    with pytest.raises(ValueError, match="不可為空"):
        compare_runs([])


# ---------------------------------------------------------------------------
# shuffle_manifests
# ---------------------------------------------------------------------------


def test_shuffle_same_seed_deterministic_byte_identical():
    first = shuffle_manifests(MANIFEST, runs=3, seed=20260805)
    second = shuffle_manifests(MANIFEST, runs=3, seed=20260805)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_shuffle_different_seed_produces_different_order():
    a = shuffle_manifests(MANIFEST, runs=2, seed=1)
    b = shuffle_manifests(MANIFEST, runs=2, seed=999)
    assert a[1]["tests"] != b[1]["tests"]
    assert sorted(a[1]["tests"]) == sorted(b[1]["tests"])  # 集合相同,只有順序不同


def test_shuffle_first_run_preserves_original_order_and_other_fields():
    runs = shuffle_manifests(MANIFEST, runs=3, seed=20260805)
    assert runs[0]["tests"] == MANIFEST["tests"]
    assert runs[0]["suite_id"] == MANIFEST["suite_id"]
    assert runs[0]["artifact_roots"] == MANIFEST["artifact_roots"]
    # 深拷貝:原始 manifest 不被任何一次呼叫動到
    assert MANIFEST["tests"] == [
        "test_cases/Characterize_A.yaml",
        "test_cases/Characterize_B.yaml",
        "test_cases/Characterize_C.yaml",
        "test_cases/Characterize_D.yaml",
    ]


def test_shuffle_invalid_runs_raises():
    with pytest.raises(ValueError):
        shuffle_manifests(MANIFEST, runs=0)


# ---------------------------------------------------------------------------
# TrustGateReport.summary() / to_json()
# ---------------------------------------------------------------------------


def test_report_summary_and_to_json_shape():
    report = TrustGateReport(
        stable={"Characterize_A": "passed", "Characterize_C": "failed"},
        kicked={"Characterize_B": ["passed", "passed", "failed"]},
    )
    assert report.summary() == "total=3 stable=2 kicked=1 stable_rate=66.7%"

    payload = json.loads(report.to_json())
    assert payload["total"] == 3
    assert payload["stable_count"] == 2
    assert payload["kicked_count"] == 1
    assert payload["stable"] == report.stable
    assert payload["kicked"] == report.kicked


def test_report_summary_handles_empty():
    report = TrustGateReport()
    assert report.summary() == "total=0 stable=0 kicked=0 stable_rate=0.0%"
