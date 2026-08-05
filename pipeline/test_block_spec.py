"""block closure 測試:合成 spec card(v2 含 calls),驗閉包/聚合/coverage。"""

import pytest

from pipeline.block_spec import build_block_spec, coverage_report, resolve_anchor


def _method(name, file="A.vb", line=10, tables=(), cond=(), calls=(), endpoints=()):
    return {
        "id": f"NS.Dao.{name}",
        "file": file,
        "line": line,
        "signature": {"name": name, "params": [], "returns": ""},
        "branch_count": 0,
        "tables": [{"name": t, "operations": ["SELECT"]} for t in tables],
        "condition_columns": list(cond),
        "unqualified_condition_columns": [],
        "endpoints": list(endpoints),
        "dynamic_sql": False,
        "calls": list(calls),
    }


SPEC = {"methods": [
    _method("SettleOrder", file="Settle.vb", line=120,
            tables=("T_ORDER",), cond=("T_ORDER.STATUS_CD",),
            calls=("LoadCustomer", "PostPayment", "Log")),
    _method("LoadCustomer", tables=("T_CUSTOMER",), cond=("T_CUSTOMER.COUNTRY_CD",)),
    _method("PostPayment", endpoints=({"kind": "http", "url_hint": "/payments"},),
            calls=("Log",)),
    _method("Unrelated", tables=("T_PRODUCT",)),
]}


def test_closure_follows_calls_and_unions():
    block = build_block_spec(SPEC, "Settlement", [{"function": "SettleOrder"}])
    assert "NS.Dao.SettleOrder" in block.method_ids
    assert "NS.Dao.LoadCustomer" in block.method_ids
    assert "NS.Dao.PostPayment" in block.method_ids
    assert "NS.Dao.Unrelated" not in block.method_ids
    assert set(block.tables) == {"T_ORDER", "T_CUSTOMER"}
    assert block.condition_columns == ["T_CUSTOMER.COUNTRY_CD", "T_ORDER.STATUS_CD"]
    assert block.endpoints == [{"kind": "http", "url_hint": "/payments"}]
    assert block.unresolved_calls == ["Log"]  # 外部呼叫,不猜,揭露


def test_file_lines_anchor():
    hits = resolve_anchor(SPEC, {"file": "Settle.vb", "lines": "100-150"})
    assert [m["signature"]["name"] for m in hits] == ["SettleOrder"]
    assert resolve_anchor(SPEC, {"file": "Settle.vb", "lines": "1-50"}) == []


def test_anchor_miss_is_reported_not_swallowed():
    block = build_block_spec(SPEC, "B", [{"function": "NoSuchFn"},
                                         {"function": "LoadCustomer"}])
    assert block.anchor_misses == [{"function": "NoSuchFn"}]
    assert block.method_ids == ["NS.Dao.LoadCustomer"]


def test_v1_card_without_calls_is_anchor_only():
    v1 = {"methods": [
        {k: v for k, v in _method("A", calls=("B",)).items() if k != "calls"},
        _method("B", tables=("T_ORDER",)),
    ]}
    block = build_block_spec(v1, "B", [{"function": "A"}])
    assert block.method_ids == ["NS.Dao.A"]  # 無邊可走,閉包=錨點


def test_coverage_report_mentions_gaps():
    block = build_block_spec(SPEC, "Settlement", [{"function": "SettleOrder"},
                                                  {"function": "Nope"}])
    report = coverage_report(block)
    assert "T_ORDER" in report and "T_CUSTOMER" in report
    assert "Log" in report          # unresolved 揭露
    assert "Nope" in report         # anchor miss 揭露


def test_bad_anchor_shape_raises():
    with pytest.raises(ValueError):
        resolve_anchor(SPEC, {"nonsense": 1})
