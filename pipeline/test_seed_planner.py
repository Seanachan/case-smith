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
    _format_value,
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


def diamond_schema() -> Schema:
    """A -> B, A -> C, B -> D, C -> D 鑽石依賴。D 必須排在 B、C 之前;
    B、C 必須排在 A 之前(彼此順序不拘)。"""
    d = Table(name="D", columns=(_col("D_ID"),), primary_key=("D_ID",))
    b = Table(
        name="B",
        columns=(_col("B_ID"), _col("D_ID")),
        primary_key=("B_ID",),
        foreign_keys=(ForeignKey("FK_B_D", ("D_ID",), "D", ("D_ID",)),),
    )
    c = Table(
        name="C",
        columns=(_col("C_ID"), _col("D_ID")),
        primary_key=("C_ID",),
        foreign_keys=(ForeignKey("FK_C_D", ("D_ID",), "D", ("D_ID",)),),
    )
    a = Table(
        name="A",
        columns=(_col("A_ID"), _col("B_ID"), _col("C_ID")),
        primary_key=("A_ID",),
        foreign_keys=(
            ForeignKey("FK_A_B", ("B_ID",), "B", ("B_ID",)),
            ForeignKey("FK_A_C", ("C_ID",), "C", ("C_ID",)),
        ),
    )
    return Schema(dialect="db2", tables={t.name: t for t in (a, b, c, d)})


def shared_ref_schema() -> Schema:
    """A 有兩條 FK 都指向同一張表 D(如「下單人」「收件人」都指向同一個
    T_CUSTOMER)。鎖住既有隱含行為:兩欄拿同一個 base ID。"""
    d = Table(name="D", columns=(_col("D_ID"),), primary_key=("D_ID",))
    a = Table(
        name="A",
        columns=(_col("A_ID"), _col("D_ID_1"), _col("D_ID_2")),
        primary_key=("A_ID",),
        foreign_keys=(
            ForeignKey("FK_A_D1", ("D_ID_1",), "D", ("D_ID",)),
            ForeignKey("FK_A_D2", ("D_ID_2",), "D", ("D_ID",)),
        ),
    )
    return Schema(dialect="db2", tables={"A": a, "D": d})


def identifying_schema() -> Schema:
    """CHILD.PARENT_ID 同時是 PK 也是 FK(identifying 1:1 關係)。"""
    parent = Table(name="PARENT", columns=(_col("PARENT_ID"),), primary_key=("PARENT_ID",))
    child = Table(
        name="CHILD",
        columns=(_col("PARENT_ID"), _col("NOTE", type_="VARCHAR(10)", nullable=True)),
        primary_key=("PARENT_ID",),
        foreign_keys=(ForeignKey("FK_CHILD_PARENT", ("PARENT_ID",), "PARENT", ("PARENT_ID",)),),
    )
    return Schema(dialect="db2", tables={"PARENT": parent, "CHILD": child})


def composite_pk_cycle_schema() -> Schema:
    """X <-> Y 環,兩條邊都 nullable,選中的打斷邊(X.Y_ID)落在複合主鍵的 X 上;
    plan_base 的 deferred UPDATE 階段會因為 X 沒有單欄主鍵而 raise。Y 的
    X_ID 也是 nullable,所以 Y 的 row 建置不會搶先因懸空 FK 而 raise——失敗點
    精準落在 deferred UPDATE 那關,用來測 all-or-nothing 回滾。Z 是無關的表,
    用來確認回滾後不相關的 plan_base 呼叫不受影響。"""
    x = Table(
        name="X",
        columns=(_col("X_ID"), _col("X_SEQ"), _col("Y_ID", nullable=True)),
        primary_key=("X_ID", "X_SEQ"),
        foreign_keys=(ForeignKey("FK_X_Y", ("Y_ID",), "Y", ("Y_ID",)),),
    )
    y = Table(
        name="Y",
        columns=(_col("Y_ID"), _col("X_ID", nullable=True)),
        primary_key=("Y_ID",),
        foreign_keys=(ForeignKey("FK_Y_X", ("X_ID",), "X", ("X_ID",)),),
    )
    z = Table(name="Z", columns=(_col("Z_ID"),), primary_key=("Z_ID",))
    return Schema(dialect="db2", tables={"X": x, "Y": y, "Z": z})


def composite_pk_ref_cycle_schema() -> Schema:
    """W <-> V 環,V 是複合主鍵。打斷邊落在 W(單欄主鍵)側,deferred UPDATE
    要回填 W.V_ID = V 的 base ID——但 V 沒有單欄主鍵、永遠不會配號。修正前
    這裡靜默輸出 SET V_ID = NULL;修正後應 raise(fail-fast)。"""
    w = Table(
        name="W",
        columns=(_col("W_ID"), _col("V_ID", nullable=True)),
        primary_key=("W_ID",),
        foreign_keys=(ForeignKey("FK_W_V", ("V_ID",), "V", ("V_ID",)),),
    )
    v = Table(
        name="V",
        columns=(_col("V_ID"), _col("V_SEQ"), _col("W_ID")),
        primary_key=("V_ID", "V_SEQ"),
        foreign_keys=(ForeignKey("FK_V_W", ("W_ID",), "W", ("W_ID",)),),
    )
    return Schema(dialect="db2", tables={"W": w, "V": v})


def not_null_with_default_schema() -> Schema:
    """T.STATUS_CD 是 NOT NULL 但有 DB default,planner 不應強填,交給 DB2 自己填。"""
    t = Table(
        name="T",
        columns=(
            _col("T_ID"),
            Column(name="STATUS_CD", type="CHAR(1)", nullable=False, default="'A'"),
        ),
        primary_key=("T_ID",),
    )
    return Schema(dialect="db2", tables={"T": t})


def identity_schema() -> Schema:
    t = Table(
        name="T",
        columns=(Column(name="T_ID", type="INTEGER", nullable=False, identity=True),),
        primary_key=("T_ID",),
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
# DomainConfig.resolve_hint:hints 詞彙表(給 ModelSlot.hint,不影響填值)
# ---------------------------------------------------------------------------


def test_domain_config_hint_exact_hit():
    domain = DomainConfig(hints={"T_ORDER.STATUS_CD": "訂單狀態碼:O=開立 S=出貨 C=關閉"})
    col = Column(name="STATUS_CD", type="CHAR(1)", nullable=False)
    assert domain.resolve_hint("T_ORDER", col) == "訂單狀態碼:O=開立 S=出貨 C=關閉"


def test_domain_config_hint_pattern_hit():
    domain = DomainConfig(hints={"*.LOGIN_NM": "系統登入帳號,全大寫英文"})
    col = Column(name="LOGIN_NM", type="VARCHAR(30)", nullable=False)
    assert domain.resolve_hint("T_ACCOUNT", col) == "系統登入帳號,全大寫英文"


def test_domain_config_hint_exact_wins_over_pattern():
    domain = DomainConfig(
        hints={
            "*.STATUS_CD": "泛用狀態碼(不精確)",
            "T_ORDER.STATUS_CD": "訂單狀態碼:O=開立 S=出貨 C=關閉",
        }
    )
    col = Column(name="STATUS_CD", type="CHAR(1)", nullable=False)
    assert domain.resolve_hint("T_ORDER", col) == "訂單狀態碼:O=開立 S=出貨 C=關閉"


def test_domain_config_hint_missing_section_returns_empty_string():
    domain = DomainConfig()  # 沒有 hints 段
    col = Column(name="ANYTHING", type="INTEGER", nullable=False)
    assert domain.resolve_hint("T", col) == ""


def test_domain_config_hint_no_match_returns_empty_string():
    domain = DomainConfig(hints={"T_ORDER.STATUS_CD": "訂單狀態碼"})
    col = Column(name="OTHER_COL", type="INTEGER", nullable=False)
    assert domain.resolve_hint("T_OTHER", col) == ""


def test_domain_config_from_yaml_reads_hints_section():
    path = REPO_ROOT / "domain" / "domain.example.yaml"
    domain = DomainConfig.from_yaml(str(path))
    status_col = Column(name="STATUS_CD", type="CHAR(1)", nullable=False)
    login_col = Column(name="LOGIN_NM", type="VARCHAR(30)", nullable=False)
    assert domain.resolve_hint("T_ORDER", status_col) == "訂單狀態碼:O=開立 S=出貨 C=關閉"
    assert domain.resolve_hint("T_ACCOUNT", login_col)  # pattern 命中,非空即可


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


def test_model_slot_hint_filled_from_domain_config(ecommerce_schema: Schema):
    domain = DomainConfig(hints={"T_ORDER.STATUS_CD": "訂單狀態碼:O=開立 S=出貨 C=關閉"})
    planner = SeedPlanner(ecommerce_schema, domain=domain, ask_model={"T_ORDER.STATUS_CD"})
    plan = planner.plan_base(["T_ORDER"])
    order_row = next(r for r in plan.rows if r.table == "T_ORDER")

    assert order_row.slots[0].hint == "訂單狀態碼:O=開立 S=出貨 C=關閉"


def test_model_slot_as_prompt_fact_includes_hint_text(ecommerce_schema: Schema):
    domain = DomainConfig(hints={"T_ORDER.STATUS_CD": "訂單狀態碼:O=開立 S=出貨 C=關閉"})
    planner = SeedPlanner(ecommerce_schema, domain=domain, ask_model={"T_ORDER.STATUS_CD"})
    plan = planner.plan_base(["T_ORDER"])
    order_row = next(r for r in plan.rows if r.table == "T_ORDER")

    fact = order_row.slots[0].as_prompt_fact()
    assert "訂單狀態碼" in fact


def test_model_slot_hint_empty_when_no_hint_configured(ecommerce_schema: Schema):
    planner = SeedPlanner(ecommerce_schema, ask_model={"T_ORDER.STATUS_CD"})  # 沒給 domain
    plan = planner.plan_base(["T_ORDER"])
    order_row = next(r for r in plan.rows if r.table == "T_ORDER")

    assert order_row.slots[0].hint == ""
    assert "; " not in order_row.slots[0].as_prompt_fact()  # 空 hint 不附加分隔符


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
    assert insert_lines[0].startswith("INSERT INTO APP.T_CUSTOMER")
    assert insert_lines[1].startswith("INSERT INTO APP.T_ORDER")

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
    assert "UPDATE APP.T_ACCOUNT SET PROFILE_ID" in sql


# ---------------------------------------------------------------------------
# 審查修正:topo 順序補測試(鑽石依賴、共用參照)
# ---------------------------------------------------------------------------


def test_topological_order_diamond_dependency():
    schema = diamond_schema()
    order, deferred = topological_order(schema, {"A", "B", "C", "D"})
    assert order.index("D") < order.index("B")
    assert order.index("D") < order.index("C")
    assert order.index("B") < order.index("A")
    assert order.index("C") < order.index("A")
    assert deferred == []


def test_two_fks_to_same_table_share_base_id():
    schema = shared_ref_schema()
    planner = SeedPlanner(schema)
    plan = planner.plan_base(["A"])
    row = next(r for r in plan.rows if r.table == "A")
    assert row.values["D_ID_1"] == row.values["D_ID_2"]


# ---------------------------------------------------------------------------
# 審查修正 #1(blocker):懸空 FK 不可靜默填預設
# ---------------------------------------------------------------------------


def test_plan_case_dangling_not_null_fk_raises_without_base():
    schema = chain_schema()
    planner = SeedPlanner(schema)
    with pytest.raises(ValueError) as exc_info:
        planner.plan_case("A", "case1")
    message = str(exc_info.value)
    assert "A" in message and "B_ID" in message and "B" in message


def test_plan_case_nullable_fk_left_null_when_dangling(ecommerce_schema: Schema):
    planner = SeedPlanner(ecommerce_schema)
    row = planner.plan_case("T_ACCOUNT", "case1")
    assert "PROFILE_ID" not in row.values


# ---------------------------------------------------------------------------
# 審查修正 #2(blocker):plan_base 重複呼叫不可重出 row / deferred UPDATE
# ---------------------------------------------------------------------------


def test_plan_base_repeated_call_does_not_duplicate_rows(ecommerce_schema: Schema):
    planner = SeedPlanner(ecommerce_schema)
    plan1 = planner.plan_base(["T_ORDER"])  # closure: T_ORDER, T_CUSTOMER
    plan2 = planner.plan_base(["T_ORDER_ITEM"])  # closure 含 T_ORDER, T_CUSTOMER(已配過號)

    assert {r.table for r in plan1.rows} == {"T_CUSTOMER", "T_ORDER"}
    assert {r.table for r in plan2.rows} == {"T_ORDER_ITEM", "T_PRODUCT"}
    assert plan2.order == [r.table for r in plan2.rows]

    order_id = next(r for r in plan1.rows if r.table == "T_ORDER").values["ORDER_ID"]
    item_row = next(r for r in plan2.rows if r.table == "T_ORDER_ITEM")
    assert item_row.values["ORDER_ID"] == order_id


def test_plan_base_repeated_call_does_not_duplicate_deferred_update(ecommerce_schema: Schema):
    planner = SeedPlanner(ecommerce_schema)
    plan1 = planner.plan_base(["T_ACCOUNT", "T_PROFILE"])
    plan2 = planner.plan_base(["T_ACCOUNT", "T_PROFILE"])

    assert len(plan1.deferred_updates) == 1
    assert plan2.rows == []
    assert plan2.deferred_updates == []


# ---------------------------------------------------------------------------
# 審查修正 #3(major):數值 quoting 依宣告型別,不依 runtime type
# ---------------------------------------------------------------------------


def test_format_value_float_domain_config_outputs_bare_decimal(ecommerce_schema: Schema):
    domain = DomainConfig(exact={"T_PRODUCT.UNIT_PRICE": 19.99})
    planner = SeedPlanner(ecommerce_schema, domain=domain)
    plan = planner.plan_base(["T_PRODUCT"])
    sql = emit_sql(plan, ecommerce_schema)

    assert "19.99" in sql
    assert "'19.99'" not in sql


# ---------------------------------------------------------------------------
# 審查修正 #4(major):NOT NULL + DB default 不強填
# ---------------------------------------------------------------------------


def test_not_null_column_with_default_is_omitted_from_insert():
    schema = not_null_with_default_schema()
    planner = SeedPlanner(schema)
    plan = planner.plan_base(["T"])
    row = next(r for r in plan.rows if r.table == "T")

    assert "STATUS_CD" not in row.values
    sql = emit_sql(plan, schema)
    assert "STATUS_CD" not in sql


# ---------------------------------------------------------------------------
# 審查修正 #5(major):self-loop 不出 UPDATE,跨表環仍出
# ---------------------------------------------------------------------------


def test_self_loop_produces_no_deferred_update():
    schema = self_loop_schema(nullable=True)
    planner = SeedPlanner(schema)
    plan = planner.plan_base(["T"])

    assert plan.deferred_updates == []
    sql = emit_sql(plan, schema)
    assert "UPDATE" not in sql
    assert "PARENT_ID" not in sql  # 該欄整個沒進 INSERT 欄位清單,維持 NULL


def test_cross_table_cycle_still_produces_deferred_update(ecommerce_schema: Schema):
    planner = SeedPlanner(ecommerce_schema)
    plan = planner.plan_base(["T_ACCOUNT", "T_PROFILE"])
    assert len(plan.deferred_updates) == 1


# ---------------------------------------------------------------------------
# 審查修正 #6(major):identity 欄位 → OVERRIDING SYSTEM VALUE
# ---------------------------------------------------------------------------


def test_identity_column_gets_overriding_system_value():
    schema = identity_schema()
    planner = SeedPlanner(schema)
    plan = planner.plan_base(["T"])
    sql = emit_sql(plan, schema)

    assert "OVERRIDING SYSTEM VALUE" in sql
    assert sql.index("OVERRIDING SYSTEM VALUE") < sql.index("VALUES")


# ---------------------------------------------------------------------------
# 審查修正 #7(minor):PK 同時是 FK(identifying 1:1)沿用 ID
# ---------------------------------------------------------------------------


def test_pk_is_fk_reuses_parent_id():
    schema = identifying_schema()
    planner = SeedPlanner(schema)
    plan = planner.plan_base(["CHILD"])

    parent_row = next(r for r in plan.rows if r.table == "PARENT")
    child_row = next(r for r in plan.rows if r.table == "CHILD")
    assert child_row.values["PARENT_ID"] == parent_row.values["PARENT_ID"]


def test_pk_is_fk_dangling_raises():
    schema = identifying_schema()
    planner = SeedPlanner(schema)
    with pytest.raises(ValueError, match="CHILD"):
        planner.plan_case("CHILD", "case_a")


# ---------------------------------------------------------------------------
# 補防呆 #8:ask_model 白名單打錯字 → raise
# ---------------------------------------------------------------------------


def test_ask_model_invalid_entry_raises(ecommerce_schema: Schema):
    with pytest.raises(ValueError, match="STATUS_CDD"):
        SeedPlanner(ecommerce_schema, ask_model={"T_ORDER.STATUS_CDD"})


def test_ask_model_unknown_table_raises(ecommerce_schema: Schema):
    with pytest.raises(ValueError, match="T_NOPE"):
        SeedPlanner(ecommerce_schema, ask_model={"T_NOPE.SOME_COL"})


# ---------------------------------------------------------------------------
# 補防呆 #9:同一 (table, case_name) 重複呼叫 plan_case() → raise;
# 同一 case_name 在不同表各留一筆增量列則是合法用法。
# ---------------------------------------------------------------------------


def test_plan_case_repeated_same_table_same_case_raises(ecommerce_schema: Schema):
    planner = SeedPlanner(ecommerce_schema)
    planner.plan_base(["T_ORDER_ITEM"])
    planner.plan_case("T_ORDER_ITEM", "case_a")
    with pytest.raises(ValueError, match="case_a"):
        planner.plan_case("T_ORDER_ITEM", "case_a")


def test_plan_case_same_case_name_different_tables_is_legal(ecommerce_schema: Schema):
    planner = SeedPlanner(ecommerce_schema)
    planner.plan_base(["T_ORDER_ITEM"])
    order_row = planner.plan_case("T_ORDER", "case_a")
    item_row = planner.plan_case("T_ORDER_ITEM", "case_a")

    assert order_row.table == "T_ORDER"
    assert item_row.table == "T_ORDER_ITEM"
    assert order_row.values["ORDER_ID"] != item_row.values["ORDER_ITEM_ID"]


# ---------------------------------------------------------------------------
# ID 全域唯一性:橫跨多表的多次 plan_case
# ---------------------------------------------------------------------------


def test_ids_globally_unique_across_tables_and_cases(ecommerce_schema: Schema):
    planner = SeedPlanner(ecommerce_schema)
    base_plan = planner.plan_base(["T_ORDER_ITEM"])

    order_case = planner.plan_case("T_ORDER", "case_order")
    item_case_a = planner.plan_case("T_ORDER_ITEM", "case_item_a")
    item_case_b = planner.plan_case("T_ORDER_ITEM", "case_item_b")

    all_ids = [row.values[schema_pk(ecommerce_schema, row.table)] for row in base_plan.rows]
    all_ids.append(order_case.values["ORDER_ID"])
    all_ids.append(item_case_a.values["ORDER_ITEM_ID"])
    all_ids.append(item_case_b.values["ORDER_ITEM_ID"])

    assert len(all_ids) == len(set(all_ids))


def schema_pk(schema: Schema, table_name: str) -> str:
    return schema.tables[table_name].primary_key[0]


# ---------------------------------------------------------------------------
# 三輪審查修正 #1(blocker):plan_case 判重寫入時機——失敗的呼叫不留痕跡,
# 補完依賴後同一組 (table, case_name) 重試要能成功。
# ---------------------------------------------------------------------------


def test_plan_case_retry_after_dependency_filled_succeeds():
    schema = chain_schema()
    planner = SeedPlanner(schema)

    with pytest.raises(ValueError):
        planner.plan_case("A", "case1")  # B 還沒配號,懸空 FK,失敗

    # 補依賴:plan_base 讓 B/C/D 都配好號
    planner.plan_base(["A"])

    row = planner.plan_case("A", "case1")  # 同一組 (table, case_name) 重試,應該成功
    assert row.table == "A"
    assert row.values["B_ID"] is not None


# ---------------------------------------------------------------------------
# 三輪審查修正 #2(major):SeedPlan.deferred 隨 already_planned 過濾,
# self-loop 項在新表時仍保留在 deferred 裡(即使不出 UPDATE)。
# ---------------------------------------------------------------------------


def test_plan_base_repeated_call_deferred_field_excludes_already_planned(
    ecommerce_schema: Schema,
):
    planner = SeedPlanner(ecommerce_schema)
    plan1 = planner.plan_base(["T_ACCOUNT", "T_PROFILE"])
    assert len(plan1.deferred) == 1
    assert plan1.deferred[0].table == "T_ACCOUNT"

    plan2 = planner.plan_base(["T_ACCOUNT", "T_PROFILE"])
    assert plan2.rows == []
    assert plan2.deferred_updates == []
    assert plan2.deferred == []  # 舊表(已配過號)不該出現在 deferred 裡


def test_self_loop_deferred_field_keeps_entry_but_no_update():
    schema = self_loop_schema(nullable=True)
    planner = SeedPlanner(schema)
    plan = planner.plan_base(["T"])

    assert len(plan.deferred) == 1
    assert plan.deferred[0].table == "T"
    assert plan.deferred_updates == []  # self-loop 不出 UPDATE,但 deferred 項保留


# ---------------------------------------------------------------------------
# 三輪審查修正 #3(major):型別解析容忍度 + runtime type 保底 fallback
# ---------------------------------------------------------------------------


def test_format_value_recognizes_dec_and_num_aliases():
    t = Table(
        name="T",
        columns=(
            _col("T_ID"),
            Column(name="AMT1", type="DEC(10,2)", nullable=True),
            Column(name="AMT2", type="NUM", nullable=True),
        ),
        primary_key=("T_ID",),
    )
    assert _format_value(t, "AMT1", Decimal("19.99")) == "19.99"
    assert _format_value(t, "AMT2", 5) == "5"


def test_format_value_tolerates_whitespace_and_trailing_modifiers():
    t = Table(
        name="T",
        columns=(
            _col("T_ID"),
            Column(name="AMT", type="DECIMAL (10, 2)", nullable=True),
            Column(name="CODE", type="VARCHAR(60) FOR BIT DATA", nullable=True),
        ),
        primary_key=("T_ID",),
    )
    assert _format_value(t, "AMT", Decimal("19.99")) == "19.99"
    assert _format_value(t, "CODE", "ABC") == "'ABC'"  # 有解析出 base(VARCHAR),仍走字串 quoting


def test_format_value_unparseable_type_falls_back_to_runtime_numeric_check():
    t = Table(name="T", columns=(Column(name="MYSTERY", type="???", nullable=True),))

    assert _format_value(t, "MYSTERY", Decimal("19.99")) == "19.99"
    assert _format_value(t, "MYSTERY", 42) == "42"
    assert _format_value(t, "MYSTERY", 3.5) == "3.5"
    assert _format_value(t, "MYSTERY", "hello") == "'hello'"  # 兩層都判斷不出數值,才走字串


# ---------------------------------------------------------------------------
# 三輪審查修正 #4(major):plan_base 中途 raise 時 _base_ids 完全不變
# (all-or-nothing),不留幽靈 ID,不相關的 plan_base 呼叫也不受影響。
# ---------------------------------------------------------------------------


def test_plan_base_mid_failure_rolls_back_base_ids_atomically():
    schema = composite_pk_cycle_schema()
    planner = SeedPlanner(schema)

    with pytest.raises(ValueError, match="無單欄主鍵"):
        planner.plan_base(["X", "Y"])

    assert planner._base_ids == {}  # Y 這次配的號不該留下幽靈紀錄

    # 不相關的表不受影響,plan_base 正常運作
    plan = planner.plan_base(["Z"])
    z_id = plan.rows[0].values["Z_ID"]
    assert SeedPlanner.ID_START <= z_id <= SeedPlanner.ID_END
    assert planner._base_ids == {"Z": z_id}


# ---------------------------------------------------------------------------
# 終輪審查發現:deferred UPDATE 的 fk_value 指向複合主鍵表時,不准靜默輸出
# NULL,要 raise。(修正前 _resolved_id 用 .get() 靜默回 None → SET 欄位 = NULL)
# ---------------------------------------------------------------------------


def test_deferred_update_to_composite_pk_ref_table_raises_not_silent_null():
    schema = composite_pk_ref_cycle_schema()
    planner = SeedPlanner(schema)

    with pytest.raises(ValueError, match=r"無法解析 V 的 base ID"):
        planner.plan_base(["W"])

    # all-or-nothing 語意在這條新 raise 路徑上同樣成立
    assert planner._base_ids == {}
