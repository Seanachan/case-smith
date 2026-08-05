# ARCHITECTURE

唯一事實來源是 [`HANDOFF.md`](./HANDOFF.md)；本檔是它的架構視角整理，衝突以 HANDOFF
為準。介面細節（欄位、型別、契約）見 [`CONTRACTS.md`](./CONTRACTS.md)，這裡只講資料
怎麼流、誰負責什麼。

## 端到端資料流

```
DB2 DDL
  │  使用者的 .mjs parse script
  ▼
schema.json                         ← 契約見 schema/schema.example.json
  │
  ▼
pipeline.SeedPlanner                ← FK 傳遞閉包 → 拓撲排序（含環打斷／deferred UPDATE）
  │                                    → domain 三層 fallback 填值 → ID 配號（900000–999999）
  ├─→ SeedRow.values                 一般欄位：planner 已填好確定性值
  └─→ SeedRow.slots: List[ModelSlot] 業務語意欄位：交給模型
        │
        ▼
      orchestrator（generate.md 樣板 + as_prompt_fact()）
        │  opencode CLI 呼叫 7–8B 模型
        ▼
      扁平 JSON（{"欄位": 值, ...}，validate.py 結構閘）
        │
        ▼
      canonical object                ← 規劃中：SeedRow.values 套用模型回填值後的
                                         單一物件，尚未有獨立型別
        │
        ├─→ serializer: SQL   （已實作：pipeline.emit_sql）
        ├─→ serializer: YAML  （規劃中，未實作）
        └─→ serializer: JSON  （規劃中，未實作）
        ▼
      ARTF test case（YAML 為主 + SQL/JSON seed data；格式對齊 framework 的
                       test_case_dsl schema，見 CONTRACTS.md 底部）
```

目前只有 SQL 這條路徑跑通到底（`pipeline/seed_planner.py::emit_sql`，20 個 pytest
涵蓋）；「canonical object」與 YAML/JSON serializer 是 HANDOFF §4〈輸出鏈〉決定的目標
形狀，尚未動工。orchestrator 目前產生扁平 JSON 後即止（`orchestrator/core.py` 的
generate/patch flow），還沒有接上 planner 的 `ModelSlot`——這是 HANDOFF §6 的下一步。

## 執行模型（跑測試時觀察什麼）

```
seed DB（含 API 前置資料）
  │
  ▼
跑受測 .exe（讀寫 DB）
  │
  ▼
.exe 對 framework 提供的 mock endpoint 送 outbound API request
```

可觀察輸出有兩份，golden master／expected／`ignore_in_snapshot` 規則都要同時涵蓋：

1. **DB snapshot**——跑完後的資料庫狀態
2. **攔截的 API request**——mock endpoint 收到的請求內容

mock endpoint 由 framework 提供，不自建。golden master（跑舊碼抓現況）產生 expected
值，模型不參與這一段。

## 元件職責

| 元件 | 職責 |
|---|---|
| `extractors/dotnet/`（骨架，待實作） | Roslyn 讀 .sln，逐方法吐 spec card：簽章、參數型別、CFG 分支、`AnalyzeDataFlow`；抽 `SqlCommand`/`CommandText` 常數字串 → regex 出表名，建立「方法 ↔ 資料表」對應；抽 outbound API 呼叫點，建立「方法 ↔ endpoint」對應。這兩個對應是 planner 的輸入，不手寫 topology.yaml |
| `pipeline/`（planner／renderer／validator） | 唯一決定結構的地方：FK 閉包（`required_closure`）、拓撲排序＋環打斷（`topological_order`）、domain 三層 fallback（`DomainConfig.resolve`）、ID 配號（`IDAllocator`，base 共享／per-case 增量）、SQL 輸出（`emit_sql`）。模型完全不經過這裡的任何決策 |
| `orchestrator/`（prompt 組裝／opencode CLI／失敗分類重試／量測） | 把 `ModelSlot.as_prompt_fact()` 組進版本化 template（`generate.md`／`patch.md`），透過 `OpencodeClient` shell 出 `opencode run` 呼叫模型；`validate.py` 做扁平 JSON 結構閘；`classify.py` 分類失敗＋ retry ladder；`metrics.py` 記每次嘗試的 JSONL log，供 v1→vN 改進曲線 |
| `domain/`（跨專案時唯一要改的地方） | `domain.yaml`：業務語意值（exact／pattern）＋ snapshot 比對要忽略的欄位（`ignore_in_snapshot`，防時間戳造成假紅燈）。窄定義：不放 topology 知識——那是 Roslyn 抽的 |
| `skill/`（規劃中，未建立） | 最終會放 `SKILL.md`（路由/文件用，不直接注入 context）＋ 模型 prompt 範本；範本目前暫放 `orchestrator/templates/` |

## 模型不做什麼

7–8B 執行期模型：

- 不產生 SQL（FK 鏈、INSERT 順序、NOT NULL 填充由 planner 決定）
- 不產生 YAML（吐扁平 JSON，由 serializer 轉換——serializer 尚未實作，見上）
- 不決定命名慣例、ID 區間、欄位順序（renderer 硬編碼）
- 不「去讀某個檔案」（orchestrator 主動注入片段；7–8B 常跳過讀取步驟）
- patch 流程只回傳單一欄位 `{"field", "value"}`，不重生整份 artifact

## 失敗分類 → 修法對照

主要失敗來源是 fixture SQL（FK 違反、缺表、順序錯），根因是模型被要求直接產生 SQL，
但 FK 傳遞閉包＋約束滿足超出 7–8B 能力，且完整 schema 本來就不在它 context 裡——這類
錯誤 **retry 永遠不會成功**，必須換修法方向：

| 分類（`orchestrator/classify.py`） | 意義 | 修法 |
|---|---|---|
| SCHEMA | 輸出形狀錯（不是合法扁平 JSON） | 嚴格重問（≤2 次重試）；真正的修法是 constrained decoding |
| SQL_EXEC | fixture SQL 執行失敗 | 立刻視為 `PlannerBugError`——**retry 對這類永遠無效**，要回頭修 planner |
| SEMANTIC | 值不合理（型別對但語意荒謬） | 重試一次，帶上該 slot 的 few-shot 範例 |

混在一起診斷會修錯方向：SQL_EXEC 類錯誤如果誤判成 SCHEMA 去重試，只會一直失敗。
