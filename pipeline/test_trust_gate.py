"""trust_gate(洗牌側)單元測試:假 suite_manifest,不碰真框架執行。

result 判定測試在 pipeline/test_flaky_gate.py(判定器只有 flaky_gate 一個)。
"""

import json

import pytest

from pipeline.trust_gate import shuffle_manifests

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
