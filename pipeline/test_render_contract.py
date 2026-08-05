"""renderer + contract checker 單元測試(不經 orchestrator)。"""

import json
from pathlib import Path

import pytest
import yaml

from pipeline.contract_check import check_suite_manifest, check_test_case
from pipeline.render_artifacts import (
    CaseBundleSpec,
    apply_model_values,
    render_bundle,
    render_cleanup_sql,
    render_verify_sql,
    verify_ignore_for,
)
from pipeline.seed_planner import DomainConfig, Schema, SeedPlanner

SCHEMA_JSON = Path(__file__).resolve().parent.parent / "schema" / "schema.example.json"

SPEC = CaseBundleSpec(
    case_id="Characterize_UpdateOrderStatus_Default",
    title="Characterize UpdateOrderStatus current behaviour",
    suite_id="CASESMITH-FAKE-E2E",
)


@pytest.fixture()
def schema():
    return Schema.from_json(json.loads(SCHEMA_JSON.read_text(encoding="utf-8")))


@pytest.fixture()
def bundle(schema):
    planner = SeedPlanner(schema, DomainConfig(), ask_model=["T_ORDER.STATUS_CD"])
    base = planner.plan_base(["T_ORDER"])
    case_row = planner.plan_case("T_ORDER", SPEC.case_id)
    values = {"T_ORDER.STATUS_CD": "P"}
    return render_bundle(SPEC, schema, base, case_row, values)


def test_bundle_passes_both_contracts(bundle):
    tc = yaml.safe_load(bundle[f"test_cases/{SPEC.case_id}.yaml"])
    sm = yaml.safe_load(bundle["suite_manifest.yaml"])
    assert check_test_case(tc) == []
    assert check_suite_manifest(sm) == []


def test_seed_base_parent_table_first(bundle):
    sql = bundle["fixtures/seed_base.sql"]
    assert sql.index("INSERT INTO T_CUSTOMER") < sql.index("INSERT INTO T_ORDER")


def test_case_seed_contains_model_value(bundle):
    assert "'P'" in bundle[f"fixtures/seed_{SPEC.case_id}.sql"]


def test_verify_sql_pins_value_in_where(bundle):
    sql = bundle[f"queries/verify_{SPEC.case_id}.sql"]
    assert "STATUS_CD = 'P'" in sql
    assert "ORDER_ID = " in sql


def test_verify_sql_ignore_column_left_out(schema):
    planner = SeedPlanner(schema, DomainConfig(), ask_model=["T_ORDER.STATUS_CD"])
    planner.plan_base(["T_ORDER"])
    row = planner.plan_case("T_ORDER", "Characterize_IgnoreDemo")
    patched = apply_model_values(row, {"T_ORDER.STATUS_CD": "P"})
    sql = render_verify_sql(schema, patched, ignore=frozenset({"STATUS_CD"}))
    assert "STATUS_CD" not in sql


def test_cleanup_child_table_first_and_range_locked(schema, bundle):
    sql = bundle["fixtures/cleanup.sql"]
    assert sql.index("DELETE FROM T_ORDER ") < sql.index("DELETE FROM T_CUSTOMER ")
    assert "BETWEEN 900000 AND 999999" in sql


def test_missing_required_section_detected(bundle):
    tc = yaml.safe_load(bundle[f"test_cases/{SPEC.case_id}.yaml"])
    del tc["execute"]
    assert any("execute" in v for v in check_test_case(tc))


def test_prohibited_legacy_key_detected(bundle):
    tc = yaml.safe_load(bundle[f"test_cases/{SPEC.case_id}.yaml"])
    tc["fixtures"] = []
    assert any("fixtures" in v for v in check_test_case(tc))


def test_inline_sql_string_detected(bundle):
    tc = yaml.safe_load(bundle[f"test_cases/{SPEC.case_id}.yaml"])
    tc["setup"]["operations"][0]["inputs"]["sql"] = "DELETE FROM T_ORDER"
    assert any("sql" in v for v in check_test_case(tc))


def test_data_entry_with_both_ref_and_value_detected(bundle):
    tc = yaml.safe_load(bundle[f"test_cases/{SPEC.case_id}.yaml"])
    tc["data"]["seed_base"] = {"ref": "x", "value": "y"}
    assert any("seed_base" in v for v in check_test_case(tc))


def test_deprecated_artifact_root_detected(bundle):
    sm = yaml.safe_load(bundle["suite_manifest.yaml"])
    sm["artifact_roots"]["execution_profiles"] = "execution_profiles/"
    assert any("execution_profiles" in v for v in check_suite_manifest(sm))


# ---------------------------------------------------------------------------
# ignore_in_snapshot → verify_ignore 解析
# ---------------------------------------------------------------------------


def test_verify_ignore_fnmatch_pattern(schema):
    domain = DomainConfig(ignore_in_snapshot=["*.ORDER_DT"])
    assert verify_ignore_for(domain, schema, "T_ORDER") == frozenset({"ORDER_DT"})


def test_verify_ignore_exact_is_table_scoped(schema):
    domain = DomainConfig(ignore_in_snapshot=["T_ORDER.STATUS_CD"])
    assert verify_ignore_for(domain, schema, "T_ORDER") == frozenset({"STATUS_CD"})
    assert verify_ignore_for(domain, schema, "T_CUSTOMER") == frozenset()


def test_verify_ignore_unmatched_pattern_is_noop(schema):
    # domain.example.yaml 引用的欄位(CREATED_AT 等)不在 example schema——
    # 跨專案 config 允許含他表欄位,比對不到就是 no-op
    domain = DomainConfig.from_yaml(
        str(Path(__file__).resolve().parent.parent / "domain" / "domain.example.yaml")
    )
    assert verify_ignore_for(domain, schema, "T_CUSTOMER") == frozenset()
