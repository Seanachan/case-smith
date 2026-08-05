# ARCHITECTURE

唯一事實來源是 [`HANDOFF.md`](./HANDOFF.md)；本檔是它的架構視角整理，衝突以 HANDOFF
為準。介面細節（欄位、型別、契約）見 [`CONTRACTS.md`](./CONTRACTS.md)，這裡只講資料
怎麼流、誰負責什麼。

## 端到端資料流

```
DB2 DDL
  │  使用者的 .mjs parse script（尚未對接——E2E 路線已降為 future work，
  │   見 HANDOFF §4「E2E 路線」；目前一律用 schema/schema.example.json 假件）
  ▼
schema.json                         ← 契約見 schema/schema.example.json
  │
  ▼
pipeline.SeedPlanner                ← FK 傳遞閉包 → 拓撲排序（含環打斷／deferred UPDATE）
  │                                    → domain 三層 fallback 填值（exact／pattern／型別預設，
  │                                      含 hints 詞彙表）→ ID 配號（900000–999999）
  ├─→ SeedRow.values                 一般欄位：planner 已填好確定性值
  └─→ SeedRow.slots: List[ModelSlot] 業務語意欄位：交給模型（含 hint 一行語意描述）
        │
        ▼
      orchestrator（generate.md 樣板 + as_prompt_fact()）
        │  OpencodeClient shell 出 `opencode run`，呼叫 7–8B 模型
        ▼
      扁平 JSON（{"欄位": 值, ...}，validate.py 結構閘；失敗依 classify.py 分類重試）
        │
        ▼
      pipeline.render_artifacts.render_bundle
        （renderer：SeedPlan + model 回填的扁平 JSON 直接吃，沒有獨立的「canonical
         object」型別、也沒有分開的 YAML/SQL/JSON 三個 serializer——原規劃的中間層
         已被單一 renderer 取代，一次產出 ARTF v0.2 四類檔）
        │
        ├─→ test_cases/*.yaml          seed／verify／cleanup SQL 內嵌在 setup/verify/cleanup
        │                               區塊（emit_sql／render_verify_sql／render_cleanup_sql；
        │                               ignore_in_snapshot 落地＝verify SQL 的 WHERE 不寫該欄）
        ├─→ suite_manifest.yaml
        ├─→ provider_instances/*.yaml
        └─→ env_profiles/*.yaml
        │
        ▼
      pipeline.contract_check          零違規（check_test_case／check_suite_manifest）才算可交
        │
        ▼
      ARTF runner（Java，使用者側執行）──▶ result.json
```

`pipeline/cli.py`（conductor CLI）把 schema→planner→orchestrator→renderer→契約檢查這幾步
串成一條指令（`uv run python -m pipeline.cli --spec ... --schema ... --method ... --out ...`），
是這條資料流目前唯一的「總開關」；分步呼叫哪些 Python API 見 `docs/USAGE.md` §③+④+⑤。

## 信任閘門（result.json 之後的量測迴圈）

```
result.json（一輪跑完）
  │
  ▼
pipeline.trust_gate    suite_manifest.tests[] 洗牌成 N 份副本（確定性 seed，第 0 份保序）
  │                    → 使用者側 ARTF runner 各跑一輪 → N 份 result.json
  ▼
pipeline.flaky_gate    判定器（洗牌器與判定器分工，判定邏輯只在這一個模組）：
                         stable   N 次 status 一致（含一致 failed＝真紅，保留不踢）
                         flaky    N 次 status 不一致 → 踢除
                         blocked  任一次 blocked（前置失敗）→ 不判定，回報人工
                         missing  某些 run 缺席 → 同 flaky 處理，踢除
```

洗牌（trust_gate）與判定（flaky_gate）是刻意拆開的兩個模組：trust_gate 只管確定性洗牌，
不碰框架執行；flaky_gate 是純函式判定器，離線可測，不重複實作判定邏輯。

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

1. **DB snapshot**——跑完後的資料庫狀態（ARTF 實際做的是 row_count／存在性比對＋
   verify SQL 的 WHERE 比對，不是全欄位 snapshot diff，見 ARTF_CONTRACT.md）
2. **攔截的 API request**——mock endpoint 收到的請求內容

mock endpoint 由 framework 提供，不自建。golden master（跑舊碼抓現況）產生 expected
值，模型不參與這一段。

## 元件職責

| 元件 | 職責 |
|---|---|
| `extractors/dotnet/CaseSmith.Extractor`（v1.1 完成） | syntax-level 直接 parse `.vb`（不用 MSBuildWorkspace，理由見 CONTRACTS「spec card」節）：逐方法吐 spec card——簽章、branch_count、常數 SQL 抽出的表／欄位（`condition_columns`＝`ask_model` 白名單來源）、outbound endpoint、`dynamic_sql` 旗標。這是 planner 的輸入，不手寫 topology.yaml。跨方法資料流（semantic／block 呼叫鏈）留給 v2，見下方「block 輸入」 |
| `extractors/dotnet/CaseSmith.Mutator`（新元件） | VB 原始碼 → mutant 樹 + `manifest.json`：三類運算子（`compare_invert`／`arithmetic_swap`／`boolean_flip`），純語法樹層級操作，字串 literal 不碰（SQL 常數安全）；每個 mutant 必須 re-parse 成功才收錄，manifest 確定性排序。是**測試品質篩選閘**——用來檢驗 CaseSmith 產的測試能不能殺死行為變異，不是產生測試本身。實際「跑 mutant 殺不殺」（rebuild + run suite）是使用者側 framework 的事 |
| `pipeline/seed_planner.py`（planner） | 唯一決定結構的地方：FK 閉包（`required_closure`）、拓撲排序＋環打斷（`topological_order`）、domain 三層 fallback（`DomainConfig.resolve`，含 `resolve_hint`）、ID 配號（`IDAllocator`，base 共享／per-case 增量）、SQL 輸出（`emit_sql`）。模型完全不經過這裡的任何決策 |
| `pipeline/render_artifacts.py`（renderer） | SeedPlan ＋ 模型回填值 → ARTF v0.2 四類檔；`ignore_in_snapshot` 落地在這裡（verify SQL 的 WHERE 排除該欄，不是框架功能） |
| `pipeline/contract_check.py` | renderer 輸出對 ARTF v0.2 契約做零違規檢查，交件前的最後一道閘 |
| `pipeline/cli.py`（conductor CLI） | 把 spec+schema → bundle 串成一條指令；`--list` 列方法、`--fake` 供離線測試跳過真模型 |
| `pipeline/trust_gate.py` ＋ `pipeline/flaky_gate.py` | 信任閘門的洗牌／判定兩模組，見上方「信任閘門」節 |
| `orchestrator/`（prompt 組裝／opencode CLI／失敗分類重試／量測） | 把 `ModelSlot.as_prompt_fact()` 組進版本化 template（`generate.md`／`patch.md`），透過 `OpencodeClient` shell 出 `opencode run` 呼叫模型；`validate.py` 做扁平 JSON 結構閘；`classify.py` 分類失敗＋ retry ladder；`metrics.py::MetricsLog` 記每次嘗試的 JSONL log（`pipeline/cli.py --out` 會寫 `runs.jsonl`），供 v1→vN 改進曲線——記錄機制已存在，累積 eval 數字待多輪跑起來才有意義 |
| `domain/`（跨專案時唯一要改的地方） | `domain.yaml`：業務語意值（exact／pattern）＋ 一行語意描述詞彙表（`hints`）＋ snapshot 比對要忽略的欄位（`ignore_in_snapshot`，防時間戳造成假紅燈）。窄定義：不放 topology 知識——那是 extractor 抽的 |
| `skill/`（規劃中，未建立） | 最終會放 `SKILL.md`（路由/文件用，不直接注入 context）＋ 模型 prompt 範本；範本目前暫放 `orchestrator/templates/` |

## block 輸入（extractor v2，缺口未實作）

使用者側輸入單位不是單一方法，而是一個 **block**（一段業務描述，內含大量跨表操作，
事前不知道會用到哪些 schema／表／服務）。已定案的轉換鏈：

```
block.md（使用者手上現成的一批描述檔，維持 source of truth）
  │  開發期強模型 + 人審，一次性轉換（合規——7–8B 限制只套執行期）
  ▼
block.yaml（錨點格式：block_id + description + anchors[]，見 REQ_BLOCK_TRACING.md）
  │
  ▼
extractor v2：從 anchors 起跳做呼叫圖 transitive closure     ← 尚未實作
  │  聯集底下所有 tables/operations/condition_columns/endpoints
  ▼
block 層級 spec card（聚合結果 + per-method 明細除錯用）
```

coverage 報告（extractor 吐實際碰到的表／endpoint 清單，人對照 block.md 描述找落差）
是驗收機制，早於假綠測試現形問題。下游（planner／orchestrator／renderer）不用改——
它們只吃「表清單＋欄位白名單」，不管上游怎麼發現，現有架構已涵蓋。完整需求原文、
缺口分析（呼叫鏈閉包／SQL schema 前綴／service provider）見
[`REQ_BLOCK_TRACING.md`](./REQ_BLOCK_TRACING.md)。

## 模型不做什麼

7–8B 執行期模型：

- 不產生 SQL（FK 鏈、INSERT 順序、NOT NULL 填充由 planner 決定）
- 不產生 YAML（吐扁平 JSON，由 renderer 轉換成 ARTF v0.2 四類檔）
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
