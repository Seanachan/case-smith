# CONTRACTS

釘介面用的文件——改動這裡描述的形狀，等於改動一個既有實作依賴的契約，請同步改程式碼
或先在這裡標記「審查中」。唯一事實來源是 [`HANDOFF.md`](./HANDOFF.md)（見其 §4／§5），
本檔與 HANDOFF 衝突時以 HANDOFF 為準。

## schema JSON 契約

正本：`schema/schema.example.json`（6 張假表，含 4 層 FK 鏈＋互指環）。讀取端：
`pipeline/seed_planner.py::Schema.from_json`。

頂層：`dialect`（string，目前只有 `"db2"`）、`source`（string，產生工具名，如
`"ddl2json.mjs"`）、`tables`（array）。

`tables[]` 元素：`name`、`schema`（DB2 schema／owner）、`columns`（array）、
`primary_key`（array\<string\>）、`foreign_keys`（array）、`unique`
（array\<array\<string\>\>，契約有此欄位但 planner 目前不讀）。

`columns[]` 元素：`name`、`type`（SQL 型別字串，如 `"DECIMAL(10,0)"`／
`"VARCHAR(60)"`／`"DATE"`）、`nullable`（bool）、`default`（DDL 預設值或
`null`，**目前不影響 planner**——NOT NULL 欄位一律走 domain fallback 填值）、
`identity`（bool，**目前也不影響 planner**——identity 欄位一樣由 `IDAllocator`
配確定性 ID）。

`foreign_keys[]` 元素：`name`（約束名）、`columns`（本表欄名 array）、
`ref_table`、`ref_columns`（對方表欄名 array）。

**已知限制：組合（多欄）FK 不支援。** `required_closure`／`topological_order`／
`SeedPlanner._fk_for` 都只認單欄 FK（`len(fk.columns) == 1`）。接真實 schema 前若
存在組合 FK，必須先補這段。

## domain.yaml 契約

正本：`domain/domain.example.yaml`。讀取端：`DomainConfig.from_yaml`／`from_dict`。

- **`exact`**：`"TABLE.COLUMN": 值`，精確匹配，優先度最高。
- **`pattern`**：`"萬用字元": 值`，`fnmatch` 對 `"TABLE.COLUMN"` 比對，字典內由上到下
  第一個命中的勝出（YAML 順序即優先序）。
- **`ignore_in_snapshot`**：`"TABLE.COLUMN"` 或 pattern 字串列表，供信任閘門排除
  snapshot 欄位（防時間戳假紅燈）。**目前只保證能被載入**，比對邏輯尚未實作
  （HANDOFF §6.4）。

`exact`／`pattern` 的值可為字面值，或 `"pattern:<產生器>"` 觸發產生器；目前只支援
`pattern:[0-9]{n}`（n 個 `"0"`）與 `pattern:[A-Z]{n}`（n 個 `"A"`），其他語法直接
raise `NotImplementedError`。這是**固定填充**，不是隨機生成——`[A-Z]{8}` 永遠是
`"AAAAAAAA"`。

**三層 fallback**（`DomainConfig.resolve`）：`exact` → `pattern` fnmatch → 型別預設
（`type_default`，涵蓋 CHAR/VARCHAR/DECIMAL/NUMERIC/INTEGER/INT/SMALLINT/BIGINT/
DATE/TIME/TIMESTAMP；未知型別回傳 `None`）。空 config 一律落到型別預設層，仍可跑。

## ID 區間

`900000`–`999999`（`SeedPlanner.ID_START`/`ID_END`），`IDAllocator` 循序配號，用盡時
raise `RuntimeError`。**base fixture**：`plan_base()` 內同一 `SeedPlanner` 實例每張表
只配一次 PK 號（`self._base_ids`），之後 case 引用同一組 ID 不重配。**per-case
增量**：`plan_case(table, case_name)` 每次為該表配一個新 PK ID；列內指回 base 表的
FK 欄位用 `plan_base()` 已配好的 ID，不重配。

## ModelSlot

**正本為 `pipeline/seed_planner.py::ModelSlot`**（planner 產出，HANDOFF §5 記錄在案）：

```python
@dataclass(frozen=True)
class ModelSlot:
    table: str
    column: str
    type: str
    constraints: str   # "NOT NULL" 或 ""
    reason: str
    # as_prompt_fact() -> "{table}.{column}: {type}"（+", {constraints}" 若非空）
```

模型看到的**只有** `as_prompt_fact()` 這一行字串。模型回覆＝一個扁平 JSON 物件，每個
要求欄位對應一個 scalar 值（結構由 `orchestrator/validate.py` 把關）。patch 契約：
只回傳單一欄位 `{"field": "<name>", "value": <值>}`，`orchestrator/core.py::apply_patch`
原地替換，不重生整份 artifact。

> **已裁決（2026-08-05）**：pipeline 版為**正本**（資料層）。`orchestrator/slots.py`
> 的 `ModelSlot` 降級為 **prompt-view**——接線（HANDOFF §6.3）時由 orchestrator 從
> pipeline slot 轉出：`name` 一律導出為 `"TABLE.COLUMN"`（即模型回覆扁平 JSON 的
> key，確定性、不由模型或人另取名）、`sql_type` ← `type`、`hint`／`examples` 為
> orchestration 層選配增強（few-shot 檢索排在 fixture 修完後，屆時才填）。
> orchestrator 側改成消費 pipeline `ModelSlot`，不維持兩套定義。接線完成前本段保留。

## SeedPlanner API（**暫定，review 中**——orchestrator 接線以此為準，review 若改介面本文件同步改）

```python
class SeedPlanner:
    def __init__(self, schema: Schema, domain: DomainConfig | None = None,
                 ask_model: Iterable[str] = ()):
        # ask_model: {'TABLE.COLUMN', ...} 白名單，標記走 ModelSlot 而非純 domain fallback

    def plan_base(self, target_tables: Iterable[str]) -> SeedPlan:
        # FK 閉包 → 拓撲排序 → 逐表一列共用 base fixture

    def plan_case(self, table_name: str, case_name: str) -> SeedRow:
        # 單表一列 per-case 增量，FK 欄位引用 plan_base() 已配好的 ID


def emit_sql(plan: SeedPlan, schema: Schema) -> str:
    # 依拓撲順序輸出 INSERT，deferred UPDATE 附加在最後；DB2 方言字面值格式
```

## ARTF 輸出契約

**已抽取完成 → 正本見 [`ARTF_CONTRACT.md`](./ARTF_CONTRACT.md)**（9 題逐項附
file:line，關鍵處已抽查 framework Java 原始碼證實）。對 CaseSmith 有約束力的重點：

- renderer 至少出 **4 種檔**：`test_case.yaml` + `suite_manifest.yaml` +
  `provider_instances/*.yaml` + `env_profiles/*.yaml`；環境值（連線字串／endpoint）
  只准走 env_profile bindings，DSL 不塞 raw 值。
- 只實作 **v0.2**；`execution_profile`／`environment_binding` 已被取代，勿碰。
- seed 走 `data.<name>.ref` 指 checked-in 檔；base＋per-case 增量由 planner 自組，
  框架無此概念。
- **DB 驗證是 row_count／存在性比對，不是 snapshot diff**——欄位值要驗必須寫進
  verify SQL 的 WHERE；`ignore_in_snapshot` 的落地＝renderer 產 verify SQL 時**不把
  該欄位寫進 WHERE**（CaseSmith 的責任，非框架功能）。
- mock 比對：`matched_count` 只比 method＋path；body 比對是**全等**，`body_pattern`
  宣告未實作——expected body 含易變欄位會假紅，繞法＝該類 case 只驗 method＋path。
