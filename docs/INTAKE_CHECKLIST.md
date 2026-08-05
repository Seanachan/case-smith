# INTAKE_CHECKLIST — 明天帶回來的 markdown 該含什麼

給整理「描述真實系統的 markdown」用的檢核表。每項寫「要什麼＋為什麼（哪個元件吃）」，
勾完再帶回來，省得來回補問。唯一事實來源是 [`HANDOFF.md`](./HANDOFF.md) 與
[`CONTRACTS.md`](./CONTRACTS.md)、[`REQ_BLOCK_TRACING.md`](./REQ_BLOCK_TRACING.md)；
本檔只是把它們對「要帶什麼資料」的要求收成一張表，衝突以那三份為準。

## 系統邊界

- [ ] **系統區塊（block）清單**：每個 block 對應哪個/哪些 `.exe` 或服務、各自讀寫
      哪些 DB（哪個 schema/instance）、對外打哪些 API。→ 用來選「這次要幫哪個 block
      產測試」，也是 `REQ_BLOCK_TRACING.md` 定義的 block.md `anchors` 的資料來源。
- [ ] **block 行為描述**（自然語言即可，不用列全會用到的表）：一段話寫「這個 block
      在做什麼」＋至少一個錨點（函式名，或「檔案＋行號範圍」）。→ extractor 從錨點做
      呼叫鏈 transitive closure，聯集出實際碰到的表/欄/endpoint；markdown 描述本身是
      **驗收基準**（coverage 報告會拿實跑結果跟這段話比對，落差在這裡現形，早於假綠
      測試）。
- [ ] **跨 schema/DB instance 的情況**：block 若橫跨多個 schema，這些 schema 之間有沒有
      FK 關係？→ 影響 closure 要不要跨 schema 走，`REQ_BLOCK_TRACING.md` 標記為待釐清項。

## DB2 schema

- [ ] **DDL 樣本**，至少含：FK 宣告、有無複合（多欄）PK/FK、有無
      identity/GENERATED 欄位、有無 NOT NULL＋DEFAULT 欄位。→ 對齊
      `schema/schema.example.json` 契約形狀（見 `CONTRACTS.md`「schema JSON 契約」）。
      **複合 FK 是 planner 目前唯一的已知限制**（`required_closure`／
      `topological_order`／`SeedPlanner._fk_for` 只認單欄 FK）——有的話要先補這段，
      不然接真 schema 會直接炸。

## 受測程式的呼叫介面

- [ ] **`.exe` 的呼叫方式**：入口參數、環境變數、輸入來源（檔案／stdin／佇列）。
      → 填 ARTF `shell_command` provider 的欄位；注意 ARTF 的
      `shell_command`／`vm_runtime`／`external_runner` **都沒有 `cwd` 欄位**，工作目錄
      怎麼決定要先問清楚（`ARTF_CONTRACT.md` Q6，framework samples 也還沒有現成範例）。
- [ ] **對外 API 的 request 樣本**：至少一份 method＋path＋body。→ 給 mock 攔截與
      expected 值設計用。ARTF 的 mock body 比對是**全等**（`Map.equals`），
      `body_pattern` 契約有宣告但**未實作**——樣本裡哪些欄位是易變的（timestamp／
      UUID／流水號）要**特別標出來**，不然這類欄位一進 expected body 就會假紅。

## SQL 抽取覆蓋率

- [ ] **sample SQL**：程式內常數 SQL 的代表性樣本，**至少一個字串動態串接的例子**
      （哪怕只是 `&` 串接）。→ 驗證 extractor（`SqlAnalyzer`）的抽取規則覆蓋率。
      目前只認「同方法內單次指派」的常數變數；多次指派或跨方法傳遞一律判為非常數、
      標 `dynamic_sql: true`——要知道這條規則在真代碼上的實際命中率，需要真實樣本
      而不是假件。

## few-shot 素材

- [ ] **framework sample ↔ VB 原始碼配對**那一份（使用者手上已有）。→ 給 few-shot
      範例與 renderer 輸出對照用；沒有這份就只能靠 example 假件的形狀推。

## 模型 serving

- [ ] **7–8B 模型在公司內部怎麼 serve**：哪個 runtime（vLLM／Ollama／TGI／自建
      OpenAI-compatible endpoint…）、API 形狀、模型的確切名稱。→ 決定要不要新寫一個
      `ModelClient`（`orchestrator/client.py` 的 protocol）；目前只有 `opencode` CLI
      這條 transport，公司內部大概率要換掉，細節見
      [`CORPORATE_SETUP.md`](./CORPORATE_SETUP.md) 的「transport 換裝」節。

## 去敏感化

- [ ] **真表名／連線字串／服務網址不進這台機器的 repo**。`.gitignore` 已擋
      `domain/*.yaml`、`schema/*.json`、`schema/*.ddl`（`.example.*` 除外），但 markdown
      本身、`.mjs` 輸出、粘貼的 request 樣本都不受這條規則保護，要**自己過一輪替換**。
      建議準備一份「假名 ↔ 真名」對照表，**自留在公司內部**，不要跟著 markdown 或
      這個 repo 走。

## 附帶但非必要

- [ ] 既有的 topology／操作流程說明文件（若有）：能加速 few-shot 設計，不是這次的
      硬性門檻。
- [ ] ARTF 黃金參考 sample `samples/10-contract-baseline/mixed_wiremock_jdbc_nats/`
      在使用者環境的實際路徑，方便日後對照（`HANDOFF.md` §4 已記錄這個相對路徑）。
