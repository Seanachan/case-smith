"""CaseSmith pipeline 核心。

schema model → FK 傳遞閉包 → topo 排序(含環打斷,產生 deferred UPDATE)→
domain 值三層 fallback → seed planner(ID 配號、base/per-case 分流)→
DB2 SQL 輸出。

設計原則(見 CLAUDE.md):能用確定性程式碼做到的,絕不寫成給模型的指示。
這裡決定哪些表要有資料、INSERT 順序、FK 值、NOT NULL 怎麼填;模型只回答
`ModelSlot` 標出的少數業務欄位,其餘結構決策一律不經過模型。
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Schema model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    nullable: bool = True
    default: Optional[str] = None
    identity: bool = False


@dataclass(frozen=True)
class ForeignKey:
    name: str
    columns: Tuple[str, ...]
    ref_table: str
    ref_columns: Tuple[str, ...]


@dataclass(frozen=True)
class Table:
    name: str
    columns: Tuple[Column, ...]
    primary_key: Tuple[str, ...] = ()
    foreign_keys: Tuple[ForeignKey, ...] = ()
    unique: Tuple[Tuple[str, ...], ...] = ()
    schema_name: Optional[str] = None  # 對應 JSON 的 "schema" 欄位

    def column(self, name: str) -> Column:
        for c in self.columns:
            if c.name == name:
                return c
        raise KeyError(f"{self.name} 沒有欄位 {name}")


@dataclass(frozen=True)
class Schema:
    dialect: str
    tables: Dict[str, Table]

    @classmethod
    def from_json(cls, data: dict) -> "Schema":
        """吃 schema JSON 契約(見 schema/schema.example.json)。"""
        tables: Dict[str, Table] = {}
        for t in data.get("tables", []):
            columns = tuple(
                Column(
                    name=c["name"],
                    type=c["type"],
                    nullable=c.get("nullable", True),
                    default=c.get("default"),
                    identity=c.get("identity", False),
                )
                for c in t.get("columns", [])
            )
            foreign_keys = tuple(
                ForeignKey(
                    name=fk["name"],
                    columns=tuple(fk["columns"]),
                    ref_table=fk["ref_table"],
                    ref_columns=tuple(fk["ref_columns"]),
                )
                for fk in t.get("foreign_keys", [])
            )
            unique = tuple(tuple(u) for u in t.get("unique", []))
            tables[t["name"]] = Table(
                name=t["name"],
                columns=columns,
                primary_key=tuple(t.get("primary_key", [])),
                foreign_keys=foreign_keys,
                unique=unique,
                schema_name=t.get("schema"),
            )
        return cls(dialect=data.get("dialect", "db2"), tables=tables)


# ---------------------------------------------------------------------------
# FK 傳遞閉包
# ---------------------------------------------------------------------------


def required_closure(schema: Schema, target_tables: Iterable[str]) -> Set[str]:
    """給定目標表,回傳所有必須有 seed 資料的表集合(FK 傳遞閉包)。"""
    closure: Set[str] = set()
    stack = list(target_tables)
    while stack:
        name = stack.pop()
        if name in closure:
            continue
        if name not in schema.tables:
            raise KeyError(f"schema 中沒有表 {name}")
        closure.add(name)
        for fk in schema.tables[name].foreign_keys:
            if fk.ref_table not in closure:
                stack.append(fk.ref_table)
    return closure


# ---------------------------------------------------------------------------
# 拓撲排序(Kahn's algorithm,含 FK 環打斷)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeferredFK:
    """FK 環的打斷點:INSERT 時該欄留 NULL,環解開後補一句 UPDATE。"""

    table: str
    fk: ForeignKey


def _fk_nullable(table: Table, fk: ForeignKey) -> bool:
    return all(table.column(c).nullable for c in fk.columns)


def _find_cycle(active_edges: Dict[str, List[ForeignKey]], node_set: Set[str]) -> List[str]:
    """在卡住的子圖裡找一條實際的環,只用於組錯誤訊息。"""
    visited: Set[str] = set()

    def dfs(node: str, path: List[str]) -> Optional[List[str]]:
        if node in path:
            idx = path.index(node)
            return path[idx:] + [node]
        if node in visited:
            return None
        visited.add(node)
        for fk in active_edges.get(node, []):
            if fk.ref_table in node_set:
                result = dfs(fk.ref_table, path + [node])
                if result:
                    return result
        return None

    for start in sorted(node_set):
        result = dfs(start, [])
        if result:
            return result
    return sorted(node_set)


def topological_order(
    schema: Schema, tables: Iterable[str]
) -> Tuple[List[str], List[DeferredFK]]:
    """Kahn 演算法排 INSERT 順序(父表先於子表)。

    遇 FK 環:選一條 nullable 的 FK 邊打斷(該欄先 INSERT NULL,環解開後
    產生 deferred UPDATE 補值)。環中若無任何 nullable 邊,raise ValueError,
    訊息含環上的表名。
    """
    table_set = set(tables)
    for name in table_set:
        if name not in schema.tables:
            raise KeyError(f"schema 中沒有表 {name}")

    # 只保留指向 table_set 內、且非自我參照的 FK 邊
    active_edges: Dict[str, List[ForeignKey]] = {
        t: [
            fk
            for fk in schema.tables[t].foreign_keys
            if fk.ref_table in table_set and fk.ref_table != t
        ]
        for t in table_set
    }

    order: List[str] = []
    ordered: Set[str] = set()
    deferred: List[DeferredFK] = []

    # 自我參照一律視為單表環,直接打斷(必須 nullable)
    for t in sorted(table_set):
        for fk in schema.tables[t].foreign_keys:
            if fk.ref_table == t:
                if not _fk_nullable(schema.tables[t], fk):
                    raise ValueError(f"FK 環(自我參照)無可打斷的 nullable 邊: {t}")
                deferred.append(DeferredFK(table=t, fk=fk))

    remaining = set(table_set)
    while remaining:
        ready = sorted(
            t for t in remaining if all(fk.ref_table in ordered for fk in active_edges[t])
        )
        if ready:
            for t in ready:
                order.append(t)
                ordered.add(t)
                remaining.discard(t)
            continue

        # 卡住:remaining 內有環,找一條 nullable 邊打斷
        broken: Optional[Tuple[str, ForeignKey]] = None
        for t in sorted(remaining):
            for fk in active_edges[t]:
                if fk.ref_table in remaining and _fk_nullable(schema.tables[t], fk):
                    broken = (t, fk)
                    break
            if broken:
                break
        if broken is None:
            cycle = _find_cycle(active_edges, remaining)
            raise ValueError(f"FK 環無可打斷的 nullable 邊: {' -> '.join(cycle)}")

        t, fk = broken
        active_edges[t] = [e for e in active_edges[t] if e is not fk]
        deferred.append(DeferredFK(table=t, fk=fk))

    return order, deferred


# ---------------------------------------------------------------------------
# Domain config:三層 fallback
# ---------------------------------------------------------------------------

_PATTERN_GEN_RE = re.compile(r"^\[(0-9|A-Z)\]\{(\d+)\}$")


def _apply_generator(spec: str) -> str:
    """`pattern:` 產生器語法。目前只支援 [0-9]{n} 與 [A-Z]{n}。"""
    m = _PATTERN_GEN_RE.match(spec.strip())
    if not m:
        raise NotImplementedError(
            f"不支援的 pattern 產生器語法: {spec!r}"
            "(目前只支援 [0-9]{n} 與 [A-Z]{n})"
        )
    charclass, n_str = m.group(1), m.group(2)
    n = int(n_str)
    return ("0" if charclass == "0-9" else "A") * n


_TYPE_RE = re.compile(r"^\s*([A-Za-z]+)\s*(?:\(\s*(\d+)\s*(?:,\s*(\d+)\s*)?\))?")


def type_default(type_str: str) -> Any:
    """型別預設值(domain config 三層 fallback 的最底層),涵蓋常見 DB2 型別。"""
    m = _TYPE_RE.match(type_str.strip())
    if not m:
        return None
    base = m.group(1).upper()
    n1 = int(m.group(2)) if m.group(2) else None
    n2 = int(m.group(3)) if m.group(3) else None

    if base in ("CHAR", "VARCHAR"):
        length = n1 or 1
        return ("X" * length)[:length]
    if base in ("DECIMAL", "NUMERIC"):
        scale = n2 or 0
        return Decimal("0").scaleb(-scale) if scale else Decimal("0")
    if base in ("INTEGER", "INT", "SMALLINT", "BIGINT"):
        return 0
    if base == "DATE":
        return date(2026, 1, 1)
    if base == "TIME":
        return time(0, 0, 0)
    if base == "TIMESTAMP":
        return datetime(2026, 1, 1, 0, 0, 0)
    return None


class DomainConfig:
    """欄位值來源三層 fallback:exact("TABLE.COL") > pattern(fnmatch) > 型別預設。

    空 config(`DomainConfig()`)也要能跑,一律落到型別預設層。

    `hints` 是獨立於值填充之外的一段:給 ModelSlot 用的欄位語意描述(給模型看,
    不影響填值邏輯)。同一個 `hints` dict 裡可以混放精確 key("TABLE.COL")和
    fnmatch pattern,查詢順序比照 exact/pattern:先直接查 dict(精確 key 命中)
    ,沒中再依 YAML 宣告順序逐一 fnmatch,沒有任何 hints 段或都沒命中則回 ""。
    """

    def __init__(
        self,
        exact: Optional[Dict[str, Any]] = None,
        pattern: Optional[Dict[str, Any]] = None,
        ignore_in_snapshot: Optional[List[str]] = None,
        hints: Optional[Dict[str, str]] = None,
    ):
        self.exact = dict(exact or {})
        self.pattern = dict(pattern or {})
        self.ignore_in_snapshot = list(ignore_in_snapshot or [])
        self.hints = dict(hints or {})

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DomainConfig":
        return cls(
            exact=data.get("exact") or {},
            pattern=data.get("pattern") or {},
            ignore_in_snapshot=data.get("ignore_in_snapshot") or [],
            hints=data.get("hints") or {},
        )

    @classmethod
    def from_yaml(cls, path: str) -> "DomainConfig":
        """從 domain.yaml 載入。yaml 是 lazy import——import 這個模組時不需要 pyyaml,
        只有真的呼叫 from_yaml 時才會需要,缺套件時報清楚的錯誤訊息。"""
        try:
            import yaml  # noqa: PLC0415  # 刻意 lazy import
        except ImportError as exc:
            raise ImportError(
                "讀取 domain yaml 需要 pyyaml,請先安裝: pip install pyyaml"
            ) from exc
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    def resolve(self, table: str, column: Column) -> Any:
        key = f"{table}.{column.name}"
        if key in self.exact:
            return self._materialize(self.exact[key])
        for pat, value in self.pattern.items():
            if fnmatch.fnmatch(key, pat):
                return self._materialize(value)
        return type_default(column.type)

    def resolve_hint(self, table: str, column: Column) -> str:
        """欄位語意描述,給 `ModelSlot.hint`。找不到就回空字串,不是 None——
        `as_prompt_fact()` 用 truthy 檢查決定要不要附加這段。"""
        key = f"{table}.{column.name}"
        if key in self.hints:
            return self.hints[key]
        for pat, value in self.hints.items():
            if fnmatch.fnmatch(key, pat):
                return value
        return ""

    @staticmethod
    def _materialize(value: Any) -> Any:
        if isinstance(value, str) and value.startswith("pattern:"):
            return _apply_generator(value[len("pattern:") :])
        return value


# ---------------------------------------------------------------------------
# ModelSlot:planner 標記「要問模型」的欄位
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelSlot:
    table: str
    column: str
    type: str
    constraints: str
    reason: str
    hint: str = ""        # domain config 的欄位描述(可空)
    examples: tuple = ()  # few-shot 值,SEMANTIC 重試時由 orchestrator 注入

    @property
    def name(self) -> str:
        """canonical "Table.Column" 字串,orchestrator 用作 JSON key。"""
        return f"{self.table}.{self.column}"

    def as_prompt_fact(self) -> str:
        """給 7-8B 模型的最小事實字串:表、欄、型別、約束,不含無關資訊。"""
        fact = f"{self.table}.{self.column}: {self.type}"
        if self.constraints:
            fact += f", {self.constraints}"
        if self.hint:
            fact += f"; {self.hint}"
        return fact


# ---------------------------------------------------------------------------
# SeedPlanner:ID 配號 + base/per-case 分流 + 值填充
# ---------------------------------------------------------------------------


class IDAllocator:
    """900000-999999 區間循序配號。"""

    def __init__(self, start: int = 900000, end: int = 999999):
        self._next = start
        self._end = end

    def next(self) -> int:
        if self._next > self._end:
            raise RuntimeError(f"ID 區間已用盡(上限 {self._end})")
        value = self._next
        self._next += 1
        return value


@dataclass
class SeedRow:
    table: str
    scope: str  # "base" 或 case 名稱
    values: Dict[str, Any] = field(default_factory=dict)
    slots: List[ModelSlot] = field(default_factory=list)


@dataclass(frozen=True)
class DeferredUpdateStatement:
    table: str
    pk_column: str
    pk_value: Any
    fk_column: str
    fk_value: Any


@dataclass
class SeedPlan:
    order: List[str]
    deferred: List[DeferredFK]
    rows: List[SeedRow]
    deferred_updates: List[DeferredUpdateStatement] = field(default_factory=list)


class SeedPlanner:
    """輸入 schema + domain config + 目標表 + ask_model 欄位白名單,輸出 seed plan。

    結構決策(表/順序/FK/ID/NOT NULL 填充)全部在這裡完成;模型只看
    `SeedRow.slots` 裡的 `ModelSlot`,填的是業務語意值,之後用單欄位 patch
    覆蓋 planner 先填好的預留值(見 CLAUDE.md 的 patch 策略)。
    """

    ID_START = 900000
    ID_END = 999999

    def __init__(
        self,
        schema: Schema,
        domain: Optional[DomainConfig] = None,
        ask_model: Iterable[str] = (),
    ):
        self.schema = schema
        self.domain = domain or DomainConfig()
        self.ask_model = set(ask_model)
        self._validate_ask_model()
        self._ids = IDAllocator(self.ID_START, self.ID_END)
        self._base_ids: Dict[str, int] = {}
        self._planned_cases: Set[Tuple[str, str]] = set()

    def _validate_ask_model(self) -> None:
        """ask_model 白名單一律驗證against schema,打錯字不可靜默退回預設值。"""
        invalid = []
        for key in self.ask_model:
            table_name, _, col_name = key.partition(".")
            table = self.schema.tables.get(table_name)
            if table is None or not any(c.name == col_name for c in table.columns):
                invalid.append(key)
        if invalid:
            raise ValueError(
                f"ask_model 白名單有無效的「表.欄」項目(schema 中找不到): {sorted(invalid)}"
            )

    def _pk_column(self, table: Table) -> Optional[Column]:
        if len(table.primary_key) != 1:
            return None
        return table.column(table.primary_key[0])

    @staticmethod
    def _fk_for(table: Table, col_name: str) -> Optional[ForeignKey]:
        for fk in table.foreign_keys:
            if len(fk.columns) == 1 and fk.columns[0] == col_name:
                return fk
        return None

    def plan_base(self, target_tables: Iterable[str]) -> SeedPlan:
        """target_tables 的 FK 閉包 → 共用 base fixture。

        同一 planner 實例(= 同一 run)內,base scope 的每張表只配一次號、只出
        一次 row。重複呼叫(closure 重疊)時,已經配過號的表會被跳過——不重出
        INSERT、不重出 deferred UPDATE;只有這次呼叫新加入的表才產生 row,
        `order`/`deferred`/`deferred_updates` 都只回傳與這次新加入的表有關的
        項目(self-loop 例外:即使是新表,也只是不出 UPDATE,`deferred` 裡仍
        保留該項,因為它是真實的打斷邊)。

        ID 配號採 all-or-nothing:本次呼叫新配的號碼先寫進區域暫存
        `pending_base_ids`,整個 plan_base() 確定不會再 raise(rows 與
        deferred_updates 都建完)才一次寫回 `self._base_ids`;中途 raise(例如
        deferred 表剛好是複合主鍵,產生不了 UPDATE)不會留下部分寫入的幽靈
        ID,之後補依賴重試才能正確重跑。ID allocator(900000+ 的號碼本身)不
        回滾——區間夠大,浪費幾個號碼無妨,只回滾 `_base_ids` 的可見性。
        """
        closure = required_closure(self.schema, target_tables)
        order, deferred = topological_order(self.schema, closure)

        already_planned = set(self._base_ids)
        new_order = [t for t in order if t not in already_planned]
        new_deferred = [d for d in deferred if d.table not in already_planned]

        deferred_cols: Dict[str, Set[str]] = {}
        for d in deferred:
            deferred_cols.setdefault(d.table, set()).update(d.fk.columns)

        pending_base_ids: Dict[str, int] = {}
        rows = [
            self._build_row(
                t,
                scope="base",
                deferred_cols=deferred_cols.get(t, set()),
                pending_base_ids=pending_base_ids,
            )
            for t in new_order
        ]

        def _resolved_id(t: str) -> Optional[int]:
            return pending_base_ids.get(t, self._base_ids.get(t))

        deferred_updates: List[DeferredUpdateStatement] = []
        for d in new_deferred:
            if d.fk.ref_table == d.table:
                continue  # self-loop:維持 NULL,不產生自我參照 UPDATE
            table = self.schema.tables[d.table]
            pk_col = self._pk_column(table)
            if pk_col is None:
                raise ValueError(f"{d.table} 無單欄主鍵,無法產生 deferred UPDATE")
            pk_value = _resolved_id(d.table)
            fk_value = _resolved_id(d.fk.ref_table)
            if pk_value is None or fk_value is None:
                missing = d.table if pk_value is None else d.fk.ref_table
                raise ValueError(
                    f"deferred UPDATE {d.table}.{d.fk.columns[0]} 無法解析 {missing} 的 base ID"
                    "(該表無單欄主鍵或尚未配號),拒絕靜默輸出 NULL"
                )
            deferred_updates.append(
                DeferredUpdateStatement(
                    table=d.table,
                    pk_column=pk_col.name,
                    pk_value=pk_value,
                    fk_column=d.fk.columns[0],
                    fk_value=fk_value,
                )
            )

        # 確定不會再 raise,才一次性讓這次新配的 ID 生效。
        self._base_ids.update(pending_base_ids)

        return SeedPlan(
            order=new_order, deferred=new_deferred, rows=rows, deferred_updates=deferred_updates
        )

    def plan_case(self, table_name: str, case_name: str) -> SeedRow:
        """為單一表產生 per-case 增量列。FK 欄位引用 plan_base() 已配好的
        base ID,不重配號;PK 本身仍配新 ID(每個 case 都是獨立一列)。

        同一 (table_name, case_name) 只能呼叫一次——重複呼叫視為 orchestrator
        retry 對同一張表同一個 case 重複下 seed,直接 raise,不要默默再生一份。
        同一 case_name 在不同表各留一筆增量列是合法用法(例如一個 case 同時要
        T_ORDER 和 T_ORDER_ITEM 各一筆),不受此限制影響。

        判重的寫入時機是 `_build_row()` 成功回傳「之後」——失敗的呼叫(例如懸空
        FK)不留下判重痕跡,orchestrator 補完依賴後用同一組 (table, case_name)
        重試才不會被誤擋。
        """
        key = (table_name, case_name)
        if key in self._planned_cases:
            raise ValueError(
                f"table {table_name!r} 的 case_name {case_name!r} 已經呼叫過 "
                "plan_case(),重複呼叫視為 orchestrator retry 造成的重複 seed"
            )
        row = self._build_row(table_name, scope=case_name)
        self._planned_cases.add(key)
        return row

    def _build_row(
        self,
        table_name: str,
        scope: str,
        deferred_cols: Set[str] = frozenset(),
        pending_base_ids: Optional[Dict[str, int]] = None,
    ) -> SeedRow:
        """`pending_base_ids` 是 plan_base() 這次呼叫「還沒 commit」的暫存 ID——
        FK/PK 解析要同時看得到已經 commit 的 `self._base_ids` 和這次呼叫內、
        排在自己前面的表(topo 順序保證前面的表已經在 pending 裡)。plan_case()
        不傳這個參數,純看已 commit 的 `self._base_ids`。
        """
        table = self.schema.tables[table_name]
        pk_col = self._pk_column(table)
        values: Dict[str, Any] = {}
        slots: List[ModelSlot] = []
        pending = pending_base_ids if pending_base_ids is not None else {}

        def _base_id_for(t: str) -> Optional[int]:
            if t in pending:
                return pending[t]
            return self._base_ids.get(t)

        if pk_col is not None:
            pk_fk = self._fk_for(table, pk_col.name)
            existing = _base_id_for(table_name) if scope == "base" else None
            if scope == "base" and existing is not None:
                row_id = existing
            elif pk_fk is not None:
                # PK 同時是 FK(identifying 1:1):沿用被參照表的 base ID,不另配號。
                ref_id = _base_id_for(pk_fk.ref_table)
                if ref_id is None:
                    raise ValueError(
                        f"{table_name}.{pk_col.name} 是 PK 也是 FK(identifying 關係),"
                        f"但參照表 {pk_fk.ref_table} 尚未配號,無法沿用 ID"
                    )
                row_id = ref_id
            else:
                row_id = self._ids.next()
            if scope == "base":
                pending[table_name] = row_id
            values[pk_col.name] = row_id

        for col in table.columns:
            if pk_col is not None and col.name == pk_col.name:
                continue
            if col.name in deferred_cols:
                continue  # 環打斷處:INSERT 時留 NULL,稍後補 UPDATE(self-loop 例外,見 plan_base)

            fk = self._fk_for(table, col.name)
            if fk is not None:
                ref_id = _base_id_for(fk.ref_table)
                if ref_id is not None:
                    values[col.name] = ref_id
                elif not col.nullable:
                    raise ValueError(
                        f"{table_name}.{col.name} 是 NOT NULL FK,參照表 {fk.ref_table} "
                        "尚未配號(懸空 FK,不可靜默落到 domain 預設值)"
                    )
                # nullable 且懸空:維持不填值(NULL)
                continue

            fact_key = f"{table_name}.{col.name}"
            if fact_key in self.ask_model:
                slots.append(
                    ModelSlot(
                        table=table_name,
                        column=col.name,
                        type=col.type,
                        constraints="NOT NULL" if not col.nullable else "",
                        reason="業務語意值,由 planner 標記交模型填(patch 覆蓋預留值)",
                        hint=self.domain.resolve_hint(table_name, col),
                    )
                )
                values[col.name] = self.domain.resolve(table_name, col)  # 預留值,待 patch
                continue

            if not col.nullable and col.default is None:
                values[col.name] = self.domain.resolve(table_name, col)

        return SeedRow(table=table_name, scope=scope, values=values, slots=slots)


# ---------------------------------------------------------------------------
# emit_sql:DB2 方言 SQL 輸出
# ---------------------------------------------------------------------------


_NUMERIC_BASE_TYPES = {
    "DECIMAL",
    "NUMERIC",
    "DEC",
    "NUM",
    "INTEGER",
    "INT",
    "SMALLINT",
    "BIGINT",
    "FLOAT",
    "REAL",
    "DOUBLE",
    "DECFLOAT",
}


def _base_type_name(type_str: str) -> str:
    """解析欄位宣告型別的 base token。容忍常見雜訊:前後空白、括號內外空白
    (`DECIMAL (10, 2)`)、修飾詞尾巴(`VARCHAR(60) FOR BIT DATA`)。完全無法
    辨識出任何字母開頭的 base token 時回傳 ""(呼叫端可據此判斷「解析失敗」,
    走 runtime type 的保底邏輯,而不是靜默誤判成字串)。
    """
    m = _TYPE_RE.match(type_str.strip())
    return m.group(1).upper() if m else ""


def _format_value(table: Table, col_name: str, value: Any) -> str:
    """Quoting 依欄位「宣告型別」決定,不依 Python runtime type——DomainConfig
    可能給 float(如 19.99),仍要照 DECIMAL 宣告輸出裸數字,不可被當成字串加引號。

    型別字串完全解析失敗(拿不到任何 base token,例如缺 schema 資訊或格式
    離奇的自訂型別)時,保底 fallback 到 runtime type 判斷:int/float/Decimal
    (排除 bool)一樣輸出裸數字,float 同樣先轉 `Decimal(str(value))`。兩層都
    判斷不出數值,才落到字串 quoting。
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"

    base = _base_type_name(table.column(col_name).type)

    if base in _NUMERIC_BASE_TYPES:
        if isinstance(value, float):
            value = Decimal(str(value))  # 先轉字串再轉 Decimal,避免二進位浮點誤差
        return str(value)
    if base == "TIMESTAMP":
        return "'{:04d}-{:02d}-{:02d}-{:02d}.{:02d}.{:02d}'".format(
            value.year, value.month, value.day, value.hour, value.minute, value.second
        )
    if base == "DATE":
        return "'{:04d}-{:02d}-{:02d}'".format(value.year, value.month, value.day)
    if base == "TIME":
        return "'{:02d}.{:02d}.{:02d}'".format(value.hour, value.minute, value.second)
    if not base and isinstance(value, (int, float, Decimal)):
        # 型別解析失敗的保底層:runtime type 明顯是數值,不要誤加引號。
        if isinstance(value, float):
            value = Decimal(str(value))
        return str(value)
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def emit_sql(plan: SeedPlan, schema: Schema) -> str:
    """依 topo 順序出 INSERT(NOT NULL 無值時已由 DomainConfig 填過),
    環打斷處的 deferred UPDATE 放在所有 INSERT 之後。DB2 方言:字串單引號、
    日期 'YYYY-MM-DD'、timestamp 'YYYY-MM-DD-HH.MM.SS'。

    identity(GENERATED ... AS IDENTITY)欄位若出現在 INSERT 欄位清單裡,DB2 需要
    OVERRIDING SYSTEM VALUE 子句才允許顯式指定值。這裡假設都是 GENERATED ALWAYS;
    GENERATED BY DEFAULT 情境未實測,接真 schema 時要驗證是否仍需要這個子句。
    """
    lines: List[str] = []
    for row in plan.rows:
        table = schema.tables[row.table]
        cols = list(row.values.keys())
        col_list = ", ".join(cols)
        val_list = ", ".join(_format_value(table, c, row.values[c]) for c in cols)
        overriding = (
            " OVERRIDING SYSTEM VALUE" if any(table.column(c).identity for c in cols) else ""
        )
        lines.append(f"INSERT INTO {table.name} ({col_list}){overriding} VALUES ({val_list});")

    for du in plan.deferred_updates:
        table = schema.tables[du.table]
        pk_val = _format_value(table, du.pk_column, du.pk_value)
        fk_val = _format_value(table, du.fk_column, du.fk_value)
        lines.append(
            f"UPDATE {du.table} SET {du.fk_column} = {fk_val} "
            f"WHERE {du.pk_column} = {pk_val};"
        )

    return "\n".join(lines)
