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


def _write_block_yaml(tmp_path, anchors):
    import yaml as _yaml
    path = tmp_path / "block.yaml"
    path.write_text(_yaml.safe_dump({
        "block_id": "Settlement",
        "description": "結單流程:讀客戶、寫稽核。",
        "anchors": anchors,
    }, allow_unicode=True), encoding="utf-8")
    return str(path)


def test_block_mode_offline(tmp_path, capsys):
    # SettleOrder 閉包 → LoadCustomer 的 T_CUSTOMER;條件欄只有 PK → 無 slot
    block = _write_block_yaml(tmp_path, [{"function": "SettleOrder"}])
    rc = main(["--spec", SPEC, "--schema", SCHEMA,
               "--block", block, "--out", str(tmp_path / "out")])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert (tmp_path / "out" / "coverage.md").exists()
    assert "T_CUSTOMER" in (tmp_path / "out" / "coverage.md").read_text()
    tc_files = list((tmp_path / "out" / "bundle" / "test_cases").glob("*.yaml"))
    assert len(tc_files) == 1
    assert "Characterize_Settlement_Default" in tc_files[0].name
    assert check_test_case(yaml.safe_load(tc_files[0].read_text())) == []


def test_block_mode_all_anchors_miss_exits(tmp_path):
    block = _write_block_yaml(tmp_path, [{"function": "NoSuchFn"}])
    with pytest.raises(SystemExit) as exc:
        main(["--spec", SPEC, "--schema", SCHEMA,
              "--block", block, "--out", str(tmp_path / "out")])
    assert "閉包為空" in str(exc.value)


def test_method_and_block_mutually_exclusive(tmp_path):
    with pytest.raises(SystemExit):
        main(["--spec", SPEC, "--schema", SCHEMA,
              "--method", "GetActiveCustomer", "--block", "x.yaml",
              "--out", str(tmp_path)])
