"""E2E 假件測試:spec card → planner → orchestrator(FakeClient)→ renderer
→ 契約驗證 → patch 迴圈。全鏈不碰網路、不碰真 DB。"""

import json
from pathlib import Path

import pytest
import yaml

from orchestrator.client import FakeClient
from orchestrator.core import Orchestrator, apply_patch
from orchestrator.metrics import MetricsLog
from pipeline.contract_check import check_suite_manifest, check_test_case
from pipeline.render_artifacts import CaseBundleSpec, render_bundle, write_bundle
from pipeline.seed_planner import DomainConfig, Schema, SeedPlanner

SCHEMA_JSON = Path(__file__).resolve().parent.parent / "schema" / "schema.example.json"

# 手寫 spec card(之後由 Roslyn extractor 產):方法、觸及表、ask_model 白名單
SPEC_CARD = {
    "method": "UpdateOrderStatus",
    "tables": ["T_ORDER"],
    "ask_model": ["T_ORDER.STATUS_CD"],
    "context": (
        "Public Sub UpdateOrderStatus(orderId As Decimal, statusCd As String)\n"
        "    ' UPDATE T_ORDER SET STATUS_CD = @statusCd WHERE ORDER_ID = @orderId\n"
        "End Sub"
    ),
}

CASE_ID = "Characterize_UpdateOrderStatus_Default"


def test_full_fake_chain(tmp_path):
    schema = Schema.from_json(json.loads(SCHEMA_JSON.read_text(encoding="utf-8")))

    # 1. planner:結構決策(表、順序、FK、ID)全在確定性程式碼
    planner = SeedPlanner(schema, DomainConfig(), ask_model=SPEC_CARD["ask_model"])
    base = planner.plan_base(SPEC_CARD["tables"])
    case_row = planner.plan_case("T_ORDER", CASE_ID)
    assert case_row.slots, "ask_model 欄位應該產生 ModelSlot"

    # 2. orchestrator:模型只填 slot 值(這裡用 FakeClient 假回應)
    metrics = MetricsLog(tmp_path / "runs.jsonl")
    orch = Orchestrator(FakeClient(['{"T_ORDER.STATUS_CD": "P"}']), metrics=metrics)
    result = orch.run_generate(CASE_ID, SPEC_CARD["context"], case_row.slots)
    assert result.attempts == 1

    # 3. renderer:值 → ARTF v0.2 bundle
    spec = CaseBundleSpec(
        case_id=CASE_ID,
        title="Characterize UpdateOrderStatus current behaviour",
        suite_id="CASESMITH-FAKE-E2E",
    )
    files = render_bundle(spec, schema, base, case_row, result.values)
    write_bundle(files, tmp_path / "bundle")
    assert (tmp_path / "bundle" / "suite_manifest.yaml").exists()

    # 4. 契約驗證:兩份 YAML 對 vendored v0.2 契約零違規
    tc_doc = yaml.safe_load(files[f"test_cases/{CASE_ID}.yaml"])
    sm_doc = yaml.safe_load(files["suite_manifest.yaml"])
    assert check_test_case(tc_doc) == []
    assert check_suite_manifest(sm_doc) == []

    # 5. 模型值一路貫穿:case seed 與 verify WHERE 都釘住 'P'
    assert "'P'" in files[f"fixtures/seed_{CASE_ID}.sql"]
    assert "STATUS_CD = 'P'" in files[f"queries/verify_{CASE_ID}.sql"]

    # 6. patch 迴圈:單欄位替換 → 重 render → 新值貫穿、舊值消失
    patch_orch = Orchestrator(
        FakeClient(['{"field": "T_ORDER.STATUS_CD", "value": "X"}']), metrics=metrics
    )
    patch = patch_orch.run_patch(
        CASE_ID, dict(result.values), "STATUS_CD 'P' 與 golden master 不符",
        {s.name for s in case_row.slots},
    )
    patched_values = apply_patch(dict(result.values), patch)
    files2 = render_bundle(spec, schema, base, case_row, patched_values)
    assert "STATUS_CD = 'X'" in files2[f"queries/verify_{CASE_ID}.sql"]
    assert "'P'" not in files2[f"fixtures/seed_{CASE_ID}.sql"]

    # 7. 量測:兩次呼叫都一次過
    summary = metrics.summary()
    assert summary["first_pass_rate"] == 1.0
