"""seed_planner.py 的假 schema 測試。不接觸真實 schema/連線字串。"""

from __future__ import annotations

import json
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

import pytest

from seed_planner import (
    Column,
    DomainConfig,
    ForeignKey,
    Schema,
    SeedPlanner,
    Table,
    emit_sql,
    required_closure,
    topological_order,
    type_default,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _col(name: str, type_: str = "INTEGER", nullable: bool = False) -> Column:
    return Column(name=name, type=type_, nullable=nullable)


# ---------------------------------------------------------------------------
# fixtures:假 schema
# ---------------------------------------------------------------------------


def chain_schema() -> Schema:
    """A -> B -> C -> D 四層 FK 鏈,D 是最底層(無 FK)。"""
    d = Table(name="D", columns=(_col("D_ID"),), primary_key=("D_ID",))
    c = Table(
        name="C",
        columns=(_col("C_ID"), _col("D_ID")),
        primary_key=("C_ID",),
        foreign_keys=(ForeignKey("FK_C_D", ("D_ID",), "D", ("D_ID",)),),
    )
    b = Table(
        name="B",
        columns=(_col("B_ID"), _col("C_ID")),
        primary_key=("B_ID",),
        foreign_keys=(ForeignKey("FK_B_C", ("C_ID",), "C", ("C_ID",)),),
    )
    a = Table(
        name="A",
        columns=(_col("A_ID"), _col("B_ID")),
        primary_key=("A_ID",),
        foreign_keys=(ForeignKey("FK_A_B", ("B_ID",), "B", ("B_ID",)),),
    )
    return Schema(dialect="db2", tables={t.name: t for t in (a, b, c, d)})


def cycle_schema(nullable_break: bool = True) -> Schema:
    """X <-> Y 兩表互指的 FK 環。X.Y_ID 可設為 nullable 作為打斷點。"""
    x = Table(
        name="X",
        columns=(_col("X_ID"), _col("Y_ID", nullable=nullable_break)),
        primary_key=("X_ID",),
        foreign_keys=(ForeignKey("FK_X_Y", ("Y_ID",), "Y", ("Y_ID",)),),
    )
    y = Table(
        name="Y",
        columns=(_col("Y_ID"), _col("X_ID", nullable=False)),
        primary_key=("Y_ID",),
        foreign_keys=(ForeignKey("FK_Y_X", ("X_ID",), "X", ("X_ID",)),),
    )
    return Schema(dialect="db2", tables={"X": x, "Y": y})


def self_loop_schema(nullable: bool = True) -> Schema:
    t = Table(
        name="T",
        columns=(_col("T_ID"), _col("PARENT_ID", nullable=nullable)),
        primary_key=("T_ID",),
        foreign_keys=(ForeignKey("FK_T_PARENT", ("PARENT_ID",), "T", ("T_ID",)),),
    )
    return Schema(dialect="db2", tables={"T": t})


@pytest.fixture
def ecommerce_schema() -> Schema:
    path = REPO_ROOT / "schema" / "schema.example.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return Schema.from_json(data)


# ---------------------------------------------------------------------------
# Schema.from_json
# ---------------------------------------------------------------------------


def test_schema_from_json_reads_example_file(ecommerce_schema: Schema):
    assert set(ecommerce_schema.tables) == {
        "T_CUSTOMER",
        "T_PRODUCT",
        "T_ORDER",
        "T_ORDER_ITEM",
        "T_ACCOUNT",
        "T_PROFILE",
    }
    order = ecommerce_schema.tables["T_ORDER"]
    assert order.primary_key == ("ORDER_ID",)
    assert order.column("CUST_ID").nullable is False
    fk = order.foreign_keys[0]
    assert fk.ref_table == "T_CUSTOMER"
    assert fk.columns == ("CUST_ID",)


# ---------------------------------------------------------------------------
# required_closure
# ---------------------------------------------------------------------------


def test_required_closure_four_layer_chain():
    schema = chain_schema()
    assert required_closure(schema, ["A"]) == {"A", "B", "C", "D"}


def test_required_closure_ecommerce_order_item(ecommerce_schema: Schema):
    closure = required_closure(ecommerce_schema, ["T_ORDER_ITEM"])
    assert closure == {"T_ORDER_ITEM", "T_ORDER", "T_PRODUCT", "T_CUSTOMER"}


# ---------------------------------------------------------------------------
# topological_order
# ---------------------------------------------------------------------------


def test_topological_order_parent_before_child():
    schema = chain_schema()
    order, deferred = topological_order(schema, {"A", "B", "C", "D"})
    assert order.index("D") < order.index("C") < order.index("B") < order.index("A")
    assert deferred == []


def test_topological_order_breaks_nullable_cycle():
    schema = cycle_schema(nullable_break=True)
    order, deferred = topological_order(schema, {"X", "Y"})
    assert set(order) == {"X", "Y"}
    assert len(deferred) == 1
    assert deferred[0].table == "X"
    assert deferred[0].fk.name == "FK_X_Y"


def test_topological_order_cycle_without_nullable_edge_raises():
    schema = cycle_schema(nullable_break=False)
    with pytest.raises(ValueError) as exc_info:
        topological_order(schema, {"X", "Y"})
    message = str(exc_info.value)
    assert "X" in message and "Y" in message


def test_topological_order_self_loop_breaks_when_nullable():
    schema = self_loop_schema(nullable=True)
    order, deferred = topological_order(schema, {"T"})
    assert order == ["T"]
    assert len(deferred) == 1


def test_topological_order_self_loop_raises_when_not_nullable():
    schema = self_loop_schema(nullable=False)
    with pytest.raises(ValueError) as exc_info:
        topological_order(schema, {"T"})
    assert "T" in str(exc_info.value)


# ---------------------------------------------------------------------------
# DomainConfig:三層 fallback
# ---------------------------------------------------------------------------


def test_domain_config_exact_hit():
    domain = DomainConfig(exact={"T_ORDER.STATUS_CD": "O"})
    col = Column(name="STATUS_CD", type="CHAR(1)", nullable=False)
    assert domain.resolve("T_ORDER", col) == "O"


def test_domain_config_pattern_hit():
    domain = DomainConfig(pattern={"*.STATUS_CD": "A"})
    col = Column(name="STATUS_CD", type="CHAR(1)", nullable=False)
    assert domain.resolve("ANY_TABLE", col) == "A"


def test_domain_config_pattern_generator():
    domain = DomainConfig(
        pattern={"*.ZIP_CD": "pattern:[0-9]{8}", "*.CODE": "pattern:[A-Z]{4}"}
    )
    zip_col = Column(name="ZIP_CD", type="VARCHAR(8)", nullable=False)
    code_col = Column(name="CODE", type="VARCHAR(4)", nullable=False)
    assert domain.resolve("T", zip_col) == "00000000"
    assert domain.resolve("T", code_col) == "AAAA"


def test_domain_config_unsupported_generator_raises():
    domain = DomainConfig(pattern={"*.X": "pattern:[a-z]{3}"})
    col = Column(name="X", type="VARCHAR(3)", nullable=False)
    with pytest.raises(NotImplementedError):
        domain.resolve("T", col)


def test_type_default_covers_db2_types():
    assert type_default("CHAR(3)") == "XXX"
    assert type_default("VARCHAR(5)") == "XXXXX"
    assert type_default("DECIMAL(10,2)") == Decimal("0.00")
    assert type_default("INTEGER") == 0
    assert type_default("SMALLINT") == 0
    assert type_default("BIGINT") == 0
    assert type_default("DATE") == date(2026, 1, 1)
    assert type_default("TIME") == time(0, 0, 0)
    assert type_default("TIMESTAMP") == datetime(2026, 1, 1, 0, 0, 0)


def test_domain_config_empty_still_works_via_type_default():
    domain = DomainConfig()
    col = Column(name="ANYTHING", type="INTEGER", nullable=False)
    assert domain.resolve("T", col) == 0


def test_domain_config_from_yaml_reads_example_file():
    path = REPO_ROOT / "domain" / "domain.example.yaml"
    domain = DomainConfig.from_yaml(str(path))
    assert domain.exact["T_ORDER.STATUS_CD"] == "O"
    assert domain.ignore_in_snapshot
    zip_col = Column(name="ZIP_CD", type="VARCHAR(8)", nullable=False)
    assert domain.resolve("SOME_TABLE", zip_col) == "00000000"


# ---------------------------------------------------------------------------
# ModelSlot / SeedPlanner
# ---------------------------------------------------------------------------


def test_model_slot_whitelist_and_prompt_fact(ecommerce_schema: Schema):
    planner = SeedPlanner(ecommerce_schema, ask_model={"T_ORDER.STATUS_CD"})
    plan = planner.plan_base(["T_ORDER"])
    order_row = next(r for r in plan.rows if r.table == "T_ORDER")

    assert len(order_row.slots) == 1
    slot = order_row.slots[0]
    assert slot.table == "T_ORDER"
    assert slot.column == "STATUS_CD"
    fact = slot.as_prompt_fact()
    assert "T_ORDER" in fact and "STATUS_CD" in fact and "CHAR(1)" in fact

    # 進 slot 的 NOT NULL 欄位仍要有預留值,之後才能用單欄位 patch 覆蓋
    assert order_row.values["STATUS_CD"] is not None


def test_base_and_case_rows_share_base_id(ecommerce_schema: Schema):
    planner = SeedPlanner(ecommerce_schema)
    base_plan = planner.plan_base(["T_ORDER_ITEM"])
    order_row = next(r for r in base_plan.rows if r.table == "T_ORDER")
    base_order_id = order_row.values["ORDER_ID"]

    case_a = planner.plan_case("T_ORDER_ITEM", "case_a")
    case_b = planner.plan_case("T_ORDER_ITEM", "case_b")

    assert case_a.values["ORDER_ID"] == base_order_id
    assert case_b.values["ORDER_ID"] == base_order_id
    assert case_a.values["ORDER_ITEM_ID"] != case_b.values["ORDER_ITEM_ID"]


def test_ids_within_reserved_range(ecommerce_schema: Schema):
    planner = SeedPlanner(ecommerce_schema)
    base_plan = planner.plan_base(["T_ORDER_ITEM"])
    case_a = planner.plan_case("T_ORDER_ITEM", "case_a")

    all_ids = []
    for row in base_plan.rows:
        table = ecommerce_schema.tables[row.table]
        if table.primary_key:
            all_ids.append(row.values[table.primary_key[0]])
    all_ids.append(case_a.values["ORDER_ITEM_ID"])

    assert all(SeedPlanner.ID_START <= v <= SeedPlanner.ID_END for v in all_ids)


# ---------------------------------------------------------------------------
# emit_sql
# ---------------------------------------------------------------------------


def test_emit_sql_not_null_filled_and_insert_order(ecommerce_schema: Schema):
    planner = SeedPlanner(ecommerce_schema)
    plan = planner.plan_base(["T_ORDER"])
    sql = emit_sql(plan, ecommerce_schema)
    insert_lines = [l for l in sql.splitlines() if l.startswith("INSERT")]

    assert len(insert_lines) == len(plan.order)
    assert insert_lines[0].startswith("INSERT INTO T_CUSTOMER")
    assert insert_lines[1].startswith("INSERT INTO T_ORDER")

    for row in plan.rows:
        table = ecommerce_schema.tables[row.table]
        for col in table.columns:
            if not col.nullable and col.default is None:
                assert col.name in row.values
                assert row.values[col.name] is not None


def test_emit_sql_deferred_update_after_inserts(ecommerce_schema: Schema):
    planner = SeedPlanner(ecommerce_schema)
    plan = planner.plan_base(["T_ACCOUNT", "T_PROFILE"])
    assert len(plan.deferred) == 1

    sql = emit_sql(plan, ecommerce_schema)
    lines = sql.splitlines()
    insert_idx = [i for i, l in enumerate(lines) if l.startswith("INSERT")]
    update_idx = [i for i, l in enumerate(lines) if l.startswith("UPDATE")]

    assert update_idx, "應該要有 deferred UPDATE"
    assert max(insert_idx) < min(update_idx)
    assert "UPDATE T_ACCOUNT SET PROFILE_ID" in sql
