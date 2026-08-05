"""golden master capture 測試。evidence fixture 形狀抄自 0.2.7 實跑產物。"""

import json
from pathlib import Path

import pytest
import yaml

from pipeline.golden_master import (
    load_query_evidence,
    main,
    observed_row,
    rebuild_verify,
)
from pipeline.seed_planner import Schema

SCHEMA_JSON = Path(__file__).resolve().parent.parent / "schema" / "schema.example.json"


def _schema():
    return Schema.from_json(json.loads(SCHEMA_JSON.read_text(encoding="utf-8")))


def _evidence(sample_rows, row_count=None):
    return {
        "evidence_type": "query_evidence",
        "provider_type": "jdbc",
        "query_ref": "queries/snapshot_X.sql",
        "row_count": len(sample_rows) if row_count is None else row_count,
        "masked_sample_result": sample_rows,
        "status": "passed",
    }


def test_observed_row_full_row():
    row, dropped = observed_row(_evidence(
        [{"ORDER_ID": 900002, "CUST_ID": 900000, "STATUS_CD": "X", "ORDER_DT": None}]
    ))
    assert row["STATUS_CD"] == "X"
    assert dropped == []


def test_masked_values_dropped():
    row, dropped = observed_row(_evidence(
        [{"CUST_ID": 900000, "CUST_NM": "***", "COUNTRY_CD": "TW"}]
    ))
    assert "CUST_NM" not in row
    assert dropped == ["CUST_NM"]


def test_empty_sample_raises():
    with pytest.raises(ValueError):
        observed_row(_evidence([]))


def test_wrong_evidence_type_raises(tmp_path):
    path = tmp_path / "e.yaml"
    path.write_text(yaml.safe_dump({"evidence_type": "seed_evidence"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_query_evidence(path)


def test_rebuild_verify_pins_observed_values():
    sql = rebuild_verify(
        _schema(), "T_ORDER",
        {"ORDER_ID": 900002, "CUST_ID": 900000, "STATUS_CD": "X", "ORDER_DT": None},
    )
    assert "STATUS_CD = 'X'" in sql          # SUT 改過的現況,非 seed 值
    assert "ORDER_ID = 900002" in sql
    assert "ORDER_DT" not in sql             # None 不進 WHERE


def test_cli_rewrites_bundle_verify(tmp_path):
    run_dir = tmp_path / "RUN-1"
    ev_dir = run_dir / "provider-evidence" / "jdbc"
    ev_dir.mkdir(parents=True)
    (ev_dir / "query_read_case_row.yaml").write_text(yaml.safe_dump(_evidence(
        [{"ORDER_ID": 900002, "CUST_ID": 900000, "STATUS_CD": "Z", "ORDER_DT": None}]
    )), encoding="utf-8")
    bundle = tmp_path / "bundle"
    (bundle / "queries").mkdir(parents=True)
    (bundle / "queries" / "verify_C1.sql").write_text("SELECT 1\n", encoding="utf-8")

    rc = main([
        "--run-dir", str(run_dir), "--bundle", str(bundle),
        "--schema", str(SCHEMA_JSON), "--case", "C1", "--table", "T_ORDER",
    ])
    assert rc == 0
    rewritten = (bundle / "queries" / "verify_C1.sql").read_text(encoding="utf-8")
    assert "STATUS_CD = 'Z'" in rewritten
