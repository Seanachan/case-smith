# HANDOFF — VB.NET Regression Test Generation Skill

> 給接手的 Claude Code:這份文件是唯一需要的脈絡。
> 使用者是 NCKU 學生,有 compiler 課背景(可以用 AST / symbol table / 拓撲排序這類語彙溝通)。
> 溝通語言:繁體中文。截止日:**2026-08-31**。

---

## 1. 專案是什麼

交付物是一個 **agent skill**:教 agent 為一個大型 VB.NET 專案產生符合特定
Regression Test Framework 的 test cases(YAML 為主 + SQL/JSON seed data)。

- 執行期模型被限制在 **7–8B**(硬限制,只套在執行期;開發期工具用強模型寫,就是你)
- 目標是產出「**可信賴**」的測試,不是衝數量
- 要能**跨專案**套用(→ domain config 機制,已設計,見 §4)
- skill 內容因安全因素不能外流;使用者手上有 framework samples,其中一份配有對應的 VB 原始碼

## 2. 已存在的東西(使用者側,你看不到)

- `SKILL.md` 初版,1000+ 行 —— 目前僅作路由/文件用,**不直接注入模型 context**
- Python **orchestrator**,含 retry;真正注入的 prompt 是 `generate.md` 與 `patch.md` 兩個 template
  ——(2026-08-05 更新)原版無法取得,已在 repo `orchestrator/` 重建:失敗分類重試 +
  ModelSlot 介面 + opencode CLI transport,25 tests 全過
- DB schema + 一支能把 schema 轉成 JSON 的 parse script
- Framework samples(含一份 sample ↔ VB 原始碼配對)
- (2026-08-05 更新)Framework 本體已公開:https://github.com/Seanachan/Auto_Regression_Test_Framework
  ——Java,`schemas/` 有 v0.2 版 JSON Schema(test_case_dsl、suite_manifest、provider_contract、
  execution_profile、result 等 9 份)。**serializer 輸出格式以這些 schema 為準**,不用從 sample 逆推。

## 3. 已確認的診斷

- **主要失敗:fixture SQL**(FK 違反、缺表、順序錯)。YAML 格式沒什麼問題。
- 根因:模型被要求直接產生 fixture SQL,但 FK 傳遞閉包 + 約束滿足超出 7–8B 能力,
  且缺的資訊(完整 schema)本來就不在它 context 裡 → **這類錯誤 retry 永遠不會成功**。
- 解法方向已定:**模型一行 SQL 都不產生**。由確定性 planner 決定表/順序/FK/填充值,
  模型只填 planner 標出的少數業務欄位(ModelSlot)。

## 4. 已做的架構決定(不要重新開題)

| 決定 | 內容 |
|---|---|
| 測試隔離 | **保留 ID 區間**(如 900000–999999),非 transaction rollback |
| Fixture 粒度 | **共用 base fixture** + per-case 增量 |
| 動態 SQL | 專案內 SQL 以**常數字串**為主 → Roslyn 可抽,不是風險 |
| 跨專案機制 | **domain.yaml**,三層 fallback:exact("Table.Col") > pattern(fnmatch) > 型別預設;空 config 也能跑 |
| 命名 | case 名用 `Characterize_` 前綴,標示「現況」而非「正確」 |
| 輸出鏈 | 模型出扁平 JSON → 單一 canonical object → 三個 serializer 出 YAML/SQL/JSON(ID 對齊是結構保證) |
| patch.md | 只回傳**單一欄位** `{"field": ..., "value": ...}`,由 Python 替換;不重生整份 artifact |
| 知識注入 | 不叫 agent「去讀檔」(7–8B 常跳過);orchestrator 依步驟把片段**注入** template |
| schema 來源(2026-08-05) | DB2 export 的 DDL → 使用者的 .mjs script parse 成 JSON;**契約形狀以 `schema/schema.example.json` 為準**,.mjs 對齊它 |
| dotnet 執行(2026-08-05) | Mac 開發,dotnet 一律走 **Docker**(`mcr.microsoft.com/dotnet/sdk:9.0`),不依賴本機 SDK |
| repo 邊界(2026-08-05) | repo 保持 **private**;generate.md / patch.md 去真實表名後可進版控(利於 template 版本化綁 eval) |
| 執行模型(2026-08-05) | seed DB(+API 前置)→ 跑受測 `.exe`(讀寫 DB)→ `.exe` 對 **framework 提供的 mock endpoint** 送 API request。可觀察輸出 = **DB snapshot + 攔截的 API request** 兩份;golden master / expected / ignore 規則都要涵蓋兩者。mock 由 framework 提供,不自建 |
| topology 知識(2026-08-05) | 不手寫 topology.yaml:方法↔表、方法↔endpoint 由 Roslyn 抽進 spec.json(extractor 範圍 +抽 outbound API 呼叫點);操作流程知識從 framework samples 歸納(few-shot,排 fixture 之後)。domain.yaml 維持窄定義(欄位值 + snapshot 排除) |
| E2E 路線(2026-08-05 grill) | **全假件先通**:example schema + 手寫 spec card(跳過 extractor)+ opencode 免費模型當 transport。真 schema 使用者無法提供 → .mjs 對齊降為 future work;7–8B 合規 = opencode CLI 打得通即可 |
| ModelSlot 歸屬(2026-08-05 grill) | 正版在 `pipeline/seed_planner.py`(含 `name` property、`hint`、`examples`);orchestrator import 它,`orchestrator/slots.py` 已刪 |
| serializer 驗證(2026-08-05 grill) | 輸出以 **jsonschema**(dev dep,已加)自動對 framework v0.2 schema 驗,掛在測試裡 |
| ARTF 契約(2026-08-05,詳見 docs/ARTF_CONTRACT.md,關鍵處已抽查 Java 原始碼證實) | (1) **DB 驗證非 snapshot diff**:框架只做 row_count/存在性比對,欄位值要驗必須寫進 verify SQL 的 WHERE → `ignore_in_snapshot` 落地方式=renderer 產 verify SQL 時**不把該欄位寫進 WHERE**,是 CaseSmith 的責任,不是框架功能 (2) mock 比對:`matched_count` 只比 method+path;body 比對是**全等**(`Map.equals`),`body_pattern` 契約有宣告但**未實作** → expected request body 含易變欄位就會假紅 (3) renderer 至少出 **4 種檔**:test_case.yaml + suite_manifest.yaml + provider_instances/*.yaml + env_profiles/*.yaml;環境值只准走 env_profile bindings (4) 只用 **v0.2**;execution_profile / environment_binding 已被取代,勿實作 (5) seed 走 `data.<name>.ref` 指 checked-in 檔;base+增量由 planner 自組,框架無此概念 (6) 跑 .exe 走 shell_command / vm_runtime / external_runner,**無 cwd 欄位**、safety.access_policy 要顯式核准、samples 無現成範例——要早期實測 (7) 黃金參考:`samples/10-contract-baseline/mixed_wiremock_jdbc_nats/` |

## 5. 已寫好的程式碼(2026-08-05 重寫進 repo;舊 outputs/ 版遺失)

| 檔案 | 內容 | 狀態 |
|---|---|---|
| `pipeline/seed_planner.py` | Schema model、`Schema.from_json`、`required_closure`、`topological_order`(Kahn + nullable 環打斷 + **deferred UPDATE 真實作**)、`DomainConfig`(三層 fallback,`pattern:[0-9]{n}`/`[A-Z]{n}`)、`ModelSlot.as_prompt_fact`、`SeedPlanner`(`plan_base`/`plan_case` 兩段式,**base 共享配號已實作**)、`emit_sql(plan, schema)` | pytest 20 passed(主線實跑) |
| `schema/schema.example.json` | schema JSON **契約**(DB2 DDL → .mjs 的目標形狀);6 張假表:4 層 FK 鏈 + 互指環 | 定稿 |
| `schema/example.ddl` | 對應的 DB2 風格 DDL(.mjs parser 參考輸入) | 定稿 |
| `domain/domain.example.yaml` | exact / pattern / ignore_in_snapshot 三段範例 | 定稿的形式 |
| `pipeline/test_seed_planner.py` | 20 tests:閉包、topo、環(含自我參照)、三層 fallback、slot、共享配號、ID 區間、emit_sql | 全過 |
| `orchestrator/` | (平行 session 重建)失敗分類重試 + ModelSlot 介面 + opencode CLI transport | 自報 25 tests 過 |
| `extractors/dotnet/` | Dockerfile(sdk:9.0)+ README,**只有骨架** | 待實作 |

已知限制:**組合(多欄)FK 未支援**——closure/topo/ID 引用只認單欄 FK,
接真 schema 前若有組合 FK 必須先補。舊版三粗糙處(deferred UPDATE TODO、
共享配號、pattern 產生器)已在重寫時修掉。

## 6. 接下來的工作(優先序)

1. **接真實 schema**:把使用者 parse script 的 JSON 對齊 `Schema.from_json`
   的形狀(或改 from_json 遷就它,看哪邊便宜),跑 `test_seed_planner.py`
   換真 schema 驗證。
2. **Roslyn extractor**(C#/.NET,新元件):
   - `MSBuildWorkspace` 開 .sln → 每個方法出 spec card JSON
     (簽章、參數型別、CFG 分支、`AnalyzeDataFlow`)
   - 抽 `SqlCommand`/`CommandText` 常數字串 → regex 抽 `FROM`/`JOIN` 表名
     → 得到「方法 ↔ 資料表」對應(planner 的輸入)
   - 抽 `WHERE`/`JOIN` 子句裡的欄位 → 自動推導 `ask_model` 白名單
     (出現在條件裡的欄位 = 影響行為 = 值得問模型;其餘用填充值)
3. **orchestrator 接 planner**:generate.md 改成只問 `ModelSlot`
   (`as_prompt_fact()` 已組好最小資訊);patch.md 改單欄位回傳。
   (2026-08-05 已裁決:pipeline `ModelSlot` 為正本,orchestrator/slots.py 版降級為
   prompt-view,`name` 導出為 `"TABLE.COLUMN"`;詳見 docs/CONTRACTS.md ModelSlot 節。)
4. **信任閘門**(Python):
   - snapshot 欄位排除(讀 domain.yaml 的 `ignore_in_snapshot`)→ 防假紅燈
   - 整批**亂序跑 3 次**,不一致者踢除 → 防 flaky
   - (加分)Roslyn mutation injector 當篩選閘:砍掉抓不到任何 mutant 的空洞測試
5. **量測迴圈**:orchestrator 記錄一次通過率/錯誤分類/重試次數,
   template 版本化,綁 eval 數字。報告要的是 v1→vN 的改進曲線。

## 7. 時程建議

- 8/26 之後凍結架構,只跑 eval + 寫報告
- 範圍取捨原則:**一條端到端走通的路 > 十個半成品元件**;
  動態 SQL / LoRA / CI 整合明確標 future work
- 對 7–8B 的鐵律:**能用確定性程式碼做到的,絕不寫成給模型的指示**

## 8. 對話中反覆出現的注意事項

- 使用者的訊息偶爾會中途斷掉送出(輸入問題),遇到語意不完整先確認再往下
- 失敗要分類再修:schema 錯 → constrained decoding;SQL 執行錯 → 修 planner
  (retry 無效);語意不合理 → few-shot。混在一起會修錯方向
- RAG/向量檢索定位:few-shot 範例檢索與業務語意值,**排在 fixture 修完之後**;
  以 sample 庫的規模,結構化特徵檢索可能比 embedding 更合適
