"""總指揮 CLI 測試:真 spec card(extractor 實跑產物)+ --fake 模型值,離線全鏈。"""

from pathlib import Path

import pytest
import yaml

from pipeline.cli import main
from pipeline.contract_check import check_test_case

ROOT = Path(__file__).resolve().parent.parent
SPEC = str(ROOT / "extractors" / "spec_card.example.json")
SCHEMA = str(ROOT / "schema" / "schema.example.json")
DOMAIN = str(ROOT / "domain" / "domain.example.yaml")


def test_list_methods(capsys):
    assert main(["--spec", SPEC, "--schema", SCHEMA, "--list"]) == 0
    out = capsys.readouterr().out
    assert "DeleteCustomer" in out


def test_full_run_offline_with_slot(tmp_path, capsys):
    # GetActiveCustomer:COUNTRY_CD 非 PK/FK → 成 slot;CUST_ID 是 PK → 濾掉
    rc = main([
        "--spec", SPEC, "--schema", SCHEMA, "--domain", DOMAIN,
        "--method", "GetActiveCustomer",
        "--out", str(tmp_path),
        "--fake", '{"T_CUSTOMER.COUNTRY_CD": "TW"}',
    ])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "ask_model=['T_CUSTOMER.COUNTRY_CD']" in out
    tc_files = list((tmp_path / "bundle" / "test_cases").glob("*.yaml"))
    assert len(tc_files) == 1
    assert check_test_case(yaml.safe_load(tc_files[0].read_text())) == []
    verify_sql = next((tmp_path / "bundle" / "queries").glob("verify_*.sql")).read_text()
    assert "COUNTRY_CD = 'TW'" in verify_sql


def test_full_run_no_slot_skips_model(tmp_path, capsys):
    # DeleteCustomer:條件欄只有 PK → 白名單空 → 不呼叫模型,bundle 照出
    rc = main([
        "--spec", SPEC, "--schema", SCHEMA,
        "--method", "DeleteCustomer",
        "--out", str(tmp_path),
    ])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "跳過模型呼叫" in out
    assert (tmp_path / "bundle" / "suite_manifest.yaml").exists()


def test_unknown_method_exits_with_hint():
    with pytest.raises(SystemExit) as exc:
        main(["--spec", SPEC, "--schema", SCHEMA, "--method", "NoSuchMethod",
              "--out", "/tmp/unused"])
    assert "--list" in str(exc.value)
