# ARTF (Auto Regression Test Framework) v0.2 契約抽取報告

目標倉庫：`/private/tmp/claude-501/-Users-seanachan-case-smith/90c56071-6a18-4c8b-b654-f292fb5639e4/scratchpad/artf`（本報告中所有相對路徑皆相對於此根目錄）

來源標記：
- **[SCHEMA]** = `schemas/*.v0.2.schema.yaml`（9 份契約描述檔，注意：這些不是 JSON Schema draft，而是「規則清單」型的契約文件——required_fields / allowed values / block 行為，沒有逐欄位 type 定義）
- **[SAMPLE]** = `samples/` 下具體 YAML/JSON 實例
- **[DOC]** = `docs/02-architecture/06_artifact_contracts.md` 或 `docs/01-specs/*`（敘述性規格文件，含逐欄位語意與範例）
- **[JAVA]** = `src/main/java/...` 原始碼行為確認
- **[推論]** = 我從以上來源交叉比對得出、schema/doc 未明講的結論

---

## Q1. test_case_dsl v0.2 — 逐欄位骨架

`schemas/test_case_dsl.v0.2.schema.yaml` 本身不是逐欄位型別表，而是規則清單。逐欄位語意在 `docs/02-architecture/06_artifact_contracts.md:547-570`（表格 + Requirement Rules）。

**必填頂層欄位**（`schemas/test_case_dsl.v0.2.schema.yaml:9-19` `required_sections`，與 `docs/02-architecture/06_artifact_contracts.md:565` 一致）：
- `dsl_version`（固定 `v0.2`）
- `test_case_id`
- `status`（執行生命週期狀態，非審批狀態；允許值 `draft_skeleton`, `draft_executable`, `active`, `needs_update`, `retired` — `docs/02-architecture/06_artifact_contracts.md:872`）
- `revision`
- `targets.<target>.provider_id`
- `execute`
- `verify`
- `evidence.required`
- `runtime.timeout`
- `runtime.retry`

**選填欄位**（`docs/02-architecture/06_artifact_contracts.md:566-567`）：`labels`（報表用 opaque metadata）、`compatible_profiles`（限制可用的 Env_Profile 名單）、`data`（reusable data ref catalog，`schemas/test_case_dsl.v0.2.schema.yaml:40-49` `data_rules`）、`source_refs`（追溯用，明文規定 `runtime_resolution: prohibited` — `schemas/test_case_dsl.v0.2.schema.yaml:25-28`，即 runtime 不得依賴它）。

**條件必填**（`schemas/test_case_dsl.v0.2.schema.yaml:20-24` `conditional_sections`）：
- `setup.operations` — 需要前置資料或會變異狀態時必填
- `cleanup.operations` — setup 變異狀態且未 inline cleanup 時必填

**巢狀結構骨架**（綜合 `docs/02-architecture/06_artifact_contracts.md:575-664` 範例 + `samples/00-getting-started/golden_e2e/test_case.yaml:1-89` 實例）：

```yaml
dsl_version: v0.2
test_case_id: <string>
title: <string>                     # 樣本中常見但非 schema 明定必填 [推論: 慣例欄位]
status: active                      # enum: draft_skeleton|draft_executable|active|needs_update|retired
revision: 1                         # 整數
source_refs: { <name>: <path#anchor> }   # 選填，runtime 不解析
labels: { <key>: <value>, tags: [...] }  # 選填 opaque metadata
compatible_profiles: [<env_profile_id>, ...]  # 選填
targets:
  <target_name>:
    provider_id: <provider_id>      # 必填；禁止出現 URL/topic/DB連線字串/憑證 (docs:686)
data:                                # 選填，reviewed data ref catalog
  <name>:
    ref: <relative_path>            # 與 value 二選一 (exactly_one_source_field_required, schema:49)
    # 或
    value: <literal>
setup:
  operations:
    - id: <unique_id>
      target: <target_name>
      operation: <op_name>          # 必須是該 target 對應 provider_contract 允許的 operation
      inputs:
        <input_key>:
          ref: ${data.<name>}       # 或內嵌 JSON pointer 片段 ref: path#/json/pointer
          # 或
          value: <literal>
      cleanup:                      # 選填 inline cleanup（與 cleanup.operations[] 二擇一）
        operation: <op_name>
        inputs: {...}
      outputs: {...}                # setup 也可有 outputs（golden_e2e 範例未用但 execute 有）
execute:
  operations:
    - id: <unique_id>
      target: <target_name>
      operation: <op_name>
      inputs: { <input_key>: {ref|value: ...} }
      outputs:
        <local_output_name>: <provider_output_ref_name>   # 必填，當後續 verify/evidence 需要時
verify:
  checks:
    - id: <unique_id>
      type: <verify_type>           # 見 Q5/表格；e.g. value_equals, json_match, http_mock_called, db_record_exists
      actual: { ref: ${execute.<op_id>.outputs.<output_name>} }
      selector: <JSONPath>          # 結構化比對時用（canonical 欄位名，path/json_path 是相容別名）
      expected: <literal>           # 或
      expected_ref: <path>          # 或 <path>#/json/pointer
      target: <target_name>         # provider-backed 狀態/事件檢查需要
      operation: <op_name>          # 同上
      inputs: {...}                 # provider-backed 檢查需要（如 db_record_exists 的 query_ref）
      options:
        ignore_order: true|false
        ignore_paths: [<dotted.or.jsonpath>]
        timeout: <ISO8601 duration>
        poll_interval: <ISO8601 duration>
        normalize: <string>
        tolerance: <number>
cleanup:
  operations:
    - id: <unique_id>
      target: <target_name>
      operation: <op_name>
      inputs: {...}
evidence:
  required:
    - <relative_path_or_${...}_template>   # 見 Q7，兩種寫法混用（見下方備註）
runtime:
  timeout: <ISO8601 duration>        # e.g. PT30S, PT2M
  retry:
    max_attempts: <integer>
```

**enum 值彙整**：
- `status`: `draft_skeleton`, `draft_executable`, `active`, `needs_update`, `retired`（`docs/02-architecture/06_artifact_contracts.md:872`）
- `verify.checks[].type`: 完整分組表見 `docs/02-architecture/06_artifact_contracts.md:766-779`（Basic / Response / Structure / Collection / Numeric-Time / File / State / Event / Plugin，見 Q5）

**明文禁止的欄位**（`schemas/test_case_dsl.v0.2.schema.yaml:97-118` `prohibited_sections`）：`data_binding`, `datasets`, `fixtures`, `expected_results`, `db_seed`, `db_cleanup`, `mock_stubs`, `rp_id`, `ac_id`, `execution_target`, `package_inputs`, `oracles`, `steps`, `assertions`, `evidence_required`, `policy`, `approval_status`, `scenario`, `waiver`, `release_gate`, `risk_approval` — 這些是舊版（v1／legacy）欄位名，新 v0.2 產生器**絕不能**輸出。

**評估**：`evidence.required` 在兩份文件裡格式不一致——`docs/02-architecture/06_artifact_contracts.md:653-658` 範例用 `${execute.run_pipeline.outputs.execution_log}` 模板參照，但實際 `samples/00-getting-started/golden_e2e/test_case.yaml:74-85` 與 `samples/10-contract-baseline/mixed_wiremock_jdbc_nats/test_case.yaml:141-148` 全部用字面相對路徑（如 `logs/execution.log`, `provider-evidence/wiremock/request_journal.json`）。**[推論]** CaseSmith 的 renderer 應該採「字面相對路徑」風格，因為那是所有可執行 sample 實際使用的格式；`${...}` 寫法目前只出現在文件示範，未見於任何 `samples/` 實例。

---

## Q2. seed/fixture 機制

**[SCHEMA]** DSL 本身**不允許**內嵌 SQL/fixture/mock_stub 內容——`schemas/test_case_dsl.v0.2.schema.yaml:29-39` `prohibited_execution_artifact_keys` 明文禁止 `fixture`, `fixtures`, `sql`, `query`, `mock_mapping`, `mock_mappings`, `data`, `payload` 這些 key 直接出現在 execution artifact 裡；資料一律透過 `data.<name>.ref` 間接引用外部檔案（`schemas/test_case_dsl.v0.2.schema.yaml:40-49`）。

**具體機制（[SAMPLE] + [JAVA] 交叉確認）**：
1. **DSL 引用**：`test_case.yaml` 的 `data:` 區塊宣告 `ref: fixtures/xxx.yaml`（如 `samples/10-contract-baseline/mixed_wiremock_jdbc_nats/test_case.yaml:20-32`），`setup.operations[].inputs` 用 `${data.<name>}` 間接引用（同檔 `:38-48`）。
2. **檔案格式依 provider 類型而異，全部是「checked-in 檔案」**：
   - JDBC seed/cleanup：純 SQL 文字檔（副檔名可為 `.yaml` 但內容是 SQL），如 `samples/10-contract-baseline/mixed_wiremock_jdbc_nats/fixtures/sample_db_seed.yaml:1-4`（`create table ...; merge into ORDERS ...`）。查詢用純 `.sql` 檔，如 `fixtures/sql/find_order.sql:1-3`。
   - WireMock stub：JSON（WireMock stub mapping 格式：`request`/`response`），如 `fixtures/wiremock/payment-api/mappings.yaml:1-15`。
   - 一般 input payload：JSON，如 `fixtures/payment_request.json`, `fixtures/input.json`。
3. **DB 操作由誰做**：**[JAVA]** `src/main/java/com/specdriven/regression/provider/jdbc/JdbcProviderRuntime.java` 是唯一執行 JDBC 操作的 runtime class（`class JdbcProviderRuntime implements ProviderRuntime` 於該檔 line 37）。它讀取 `sql_ref`/`query_ref` 指向的 checked-in SQL 檔，用具名參數 `:param_name` 語法（regex `NAMED_PARAM`，line 407-417 `prepareSql`）轉成 JDBC `?` 佔位符後綁定執行，SQL 本身完全不進 DSL。
4. **WireMock stub 載入**：**[JAVA]** `WireMockHttpMockProviderRuntime.java:101-114`——`load_stubs` operation 讀取 `mock.mappings_ref` 指向的 stub 檔，直接 POST 到 WireMock 的 `/__admin/mappings` admin API。
5. **共用 base fixture + per-case 增量的對應**：**[推論]** ARTF 沒有專門的「base fixture + increment」機制。最接近的對應是：
   - Provider Contract 層的 `defaults`（如 `jdbc.yaml:30-33` 的 `default_timeout`, `strict_params`）扮演跨 case 共用設定的角色。
   - Suite 層的 `artifact_roots`（`schemas/suite_manifest.v0.2.schema.yaml:31-43`）讓多個 test case 共用同一批 `fixtures/`, `provider_instances/`, `env_profiles/` 目錄。
   - 但「一個 base seed + 每個 case 疊加差異」這種語意在 DSL/schema 裡**查無**專屬欄位；每個 test case 的 `setup.operations` 都是各自完整宣告 seed SQL ref，沒有繼承機制。CaseSmith 若要做「共用 base + per-case 增量」，需要在 planner 層（Python）自己組裝出完整 SQL ref 檔案，再讓每個 case 各自指向組好的檔案——ARTF runtime 不提供這層抽象。

---

## Q3. 執行受測程式（跑一個 .exe）

**[SCHEMA]** `execution_profile.v0.2.schema.yaml` 本身**不是**「跑一個 .exe」的欄位定義——它定義的是執行環境策略（execution_mode: local/ci/sit/preprod、dependency 替代/佈建政策），且已被 `env_profile` 取代為 compatibility-only 輸入（見 Q9）。真正「跑受測程式」的定義在 **Provider Contract** 層，透過三種 provider_type：

| provider_type | 檔案 | 適用場景 |
|---|---|---|
| `shell_command` | `docs/02-architecture/contracts/provider-contracts/shell_command.yaml:1-35` | 本機/CI shell 指令、批次程式 |
| `vm_runtime` | `docs/02-architecture/contracts/provider-contracts/vm_runtime.yaml:1-50` | 遠端 VM 上跑指令（SSH 語意，host+user binding key） |
| `external_runner` | `docs/02-architecture/contracts/provider-contracts/external_runner.yaml:1-41` | 需要額外安全審批的外部執行器（見下方 safety 區塊） |

以 `shell_command` 為例（最貼近「跑一個 .exe」）：

- **operation**：`run_batch` 或 `execute_command`（`shell_command.yaml:22-30`）
- **參數（args）**：`runner.args.*`（allowed_inputs 的一部分）
- **環境變數（env_vars）**：`runner.env.*`
- **逾時**：`runner.timeout`
- **輸入檔**：`runner.input_file`
- **輸出**：`output_refs: [exit_code, stdout, stderr, output_files, duration_ms]`
- **工作目錄**：**查無**明確的 `runner.cwd` / `working_dir` binding key——三個 runner 類契約（shell_command/vm_runtime/external_runner）都沒有這個欄位。`vm_runtime.yaml` 的 `run_command` 也只有 `vm.command`, `vm.args.*`, `vm.env.*`, `vm.timeout`，同樣無工作目錄欄位。**[推論]** ARTF 目前的三個 runner provider 都不支援顯式指定工作目錄；若 CaseSmith 需要「在指定目錄下跑 VB.NET 編譯出的 .exe」，這是一個契約缺口，需要用 `runner.args.*` 或 `runner.env.*`（如設 `CD`/自訂變數）自行處理，或者是 planner 層自己組出絕對路徑帶進 `runner.args`。
- **安全閘門**：`safety.rules`（`shell_command.yaml:11-18`）要求 `safety.access_policy.allowed_commands` 與 `safety.access_policy.allow_shell` 必填，且明文禁止 `allow_shell_true_without_approval` 這種預設值——即「跑任意 shell 指令」預設被封鎖，需要 Provider Instance 顯式宣告允許清單。`external_runner` 更嚴格，額外要求 `safety.approval.ref`（`external_runner.yaml:15-18`）且 `valid_provider_instance_shape.required_fields` 必含 `safety`（line 22）。

**runtime_modes**：`shell_command: [native, mock, stub]`；`external_runner: [native, stub]`；`vm_runtime: [native, mock]`（各自檔案 line 3）。

**[DOC]** `docs/02-architecture/06_artifact_contracts.md:711` 與 `:716` 列出 `exec_command`、`check_process` 也在 core operation catalog 內（分屬 `kubernetes_runtime`/`vm_runtime`），供 K8s/VM 場景用；不是通用「跑本機 .exe」的路徑。

**[推論]** 對 CaseSmith（VB.NET .exe，讀寫 DB）最貼近的 provider_type 應該是 `shell_command`，用 `execute_command` 或 `run_batch` operation，`runner.args.*` 帶命令列參數，`runner.env.*` 帶環境變數（含連線字串等，但要注意 ARTF 的 binding key 規則禁止在 DSL 裡放 raw endpoint/連線字串——這些應該走 Env_Profile bindings，不是 DSL inputs）。

---

## Q4. mock endpoint / API 攔截

**Provider**：`wiremock_http_mock`（`docs/02-architecture/contracts/provider-contracts/wiremock_http_mock.yaml:1-75`，與 `samples/10-contract-baseline/mixed_wiremock_jdbc_nats/provider_contracts/wiremock_http_mock.yaml:1-27` 簡化版並存）。是 provider_contract + provider_instance 兩層在管，不是 execution_profile。

**Operations**：
- `load_stubs`：載入 mock 回應規則（`mock.mappings_ref`）
- `send_http_request` / `verify_requests`：實際發送請求並驗證（`mock.request_filter`, `mock.expected_count`, `mock.body_pattern` 允許輸入；`request_journal`, `matched_count` 輸出）

**攔截到的 request 存成什麼形狀**：**[JAVA]** `WireMockHttpMockProviderRuntime.java:175-176`——直接把 WireMock admin API `/__admin/requests` 回傳的原始 journal JSON 整包寫入 `provider-evidence/wiremock/request_journal.json`。範例存檔可見 `samples/10-contract-baseline/mixed_wiremock_jdbc_nats/evidence/runs/RUN-CONTRACT-001/provider-evidence/payment-api/request_journal.yaml:1-11`（精簡後形狀：`matched_requests: [{method, path, status}]`）。

**expected request 怎麼寫**：一個 JSON 檔同時扮演「過濾器」與「期望值」雙重角色，例：`samples/20-provider-capability-p0/http/wiremock_http_mock/expected_results/expected_request.json:1-9`：
```json
{
  "method": "POST",
  "path": "/payments",
  "expected_count": 1,
  "body": { "paymentId": "PAY-001", "amount": 100, "currency": "USD" }
}
```

**怎麼比對（[JAVA] 確認，非推論）**——這裡有兩層不同粒度的比對，要分清楚：

1. **`countExpectedRequests`**（`WireMockHttpMockProviderRuntime.java:320-332`，用在 `send_http_request` operation 算 `matched_count`）：**只比對 `method` 與 `path` 完全相等**（`expectedPath.equals(...) && expectedMethod.equals(...)`），**不比對 body**。
2. **`http_mock_request_body_match` verify type**（`WireMockProviderCapabilityService.java:450-468` `requestBodyMatches`）：先用 method+path 篩出候選 request，再對 body 做 **`expectedBody.equals(actualBody)` 完全相等比對**（Java `Map.equals`，逐 key 全等，任何一個 key 不存在或值不同即不算 match）。**沒有找到**部分比對（partial match）、萬用字元、或欄位排除（ignore fields）機制用於 request body 比對——`mock.body_pattern` 這個輸入欄位雖然在契約裡宣告為 `verify_requests` 的 allowed_inputs（`wiremock_http_mock.yaml:27` 或 provider_contract 範例 `docs/.../wiremock_http_mock.yaml:27`），但**查無**任何 Java 實作讀取或使用它——`grep -rn "body_pattern" src/main/java/` 只在 schema/contract 檔案出現，實際 runtime 沒有消費這個欄位。**[推論]** `mock.body_pattern` 是契約已宣告但尚未實作的欄位（contract-ahead-of-implementation），CaseSmith 不應假設它能做部分匹配。

**結論給 CaseSmith**：body 比對是「全等」，不是部分匹配；若受測程式送出的 request body 有動態欄位（timestamp、UUID），目前 ARTF 沒有請求層級的欄位排除機制——要嘛在 planner 產生 expected body 時就精確算出動態值（例如凍結時鐘 `clock_ref: fixed://...`，見 `samples/00-getting-started/golden_e2e/env_profiles/local_golden.yaml:7`），要嘛預期會比對失敗。

---

## Q5. DB snapshot 比對

**這是最重要的一個發現**：ARTF 的 DB 驗證**不是**「全表 snapshot diff」，而是「查詢結果的 row_count / 存在性」比對，外加少量樣本列（最多 5 列）僅作為證據保存、**不參與 pass/fail 判定**。

**[JAVA] 確認**（`src/main/java/com/specdriven/regression/provider/jdbc/JdbcProviderRuntime.java`）：
- `db_query` / `db_record_exists` 共用 `executeQuery` 方法（line 196-287）。執行 checked-in SQL（`query_ref`），拿到 `ResultSet` 後：
  - `rowCount = rows.size()`（line 218，全部列都算，不限制）
  - `sampleRows = rows.stream().limit(5).toList()`（line 219，**只留最多 5 列**存進證據，且做過遮罩）
  - `db_record_exists` 的 pass/fail 判定：`matched = !recordExists || matchesExpected(rowCount, request)`（line 223）——即比對的是 **row_count 是否符合期望**（`expected.min_rows` 或 `expected.row_count`，見 `jdbc.yaml:52` allowed_inputs），**不是逐欄位比對列內容**。
  - `db_query` 本身沒有 pass/fail 邏輯，只是取得輸出（`row_count`, `sample_rows`, `query_evidence_ref`）供後續 `verify.checks` 使用。
- **[JAVA]** `AssertionEngine.java:122-154` 的 `evaluateDbRowMatches`（對應 legacy `db_row_matches` assertion type）同樣**只比對 `actualCount == expectedCount`**（line 137），不是欄位比對。
- **遮罩（masking）不是排除（ignore）**：`maskRows`/`mask` 方法（`JdbcProviderRuntime.java` 約 line 602-623）只對欄位名稱包含 `password`/`secret`/`token`/`credential`/`authorization` 的值換成 `"***"`，這是安全遮罩，**不是** CaseSmith 意義下的「動態欄位排除以避免假失敗」的機制。

**查無**的東西（明確找過，沒有）：
- 沒有 field-level `ignore_in_snapshot` 或 `exclude_fields` 選項用於 DB 列內容比對。
- 沒有全表 dump / 全表 diff 的 provider operation（`jdbc.yaml` 只有 `db_seed`, `db_cleanup`, `db_query`, `db_record_exists` 四個 operation，`jdbc.yaml:39-54`）。

**與 CaseSmith 對應**：`db_record_exists` 的 `expected.min_rows`/`expected.row_count`（`samples/10-contract-baseline/mixed_wiremock_jdbc_nats/test_case.yaml:119-120`）是「至少存在幾筆」的粗粒度驗證，不是精確值比對。若 CaseSmith 需要驗證某欄位的精確值（如 `STATUS = 'READY'`），**必須把該欄位寫進 SQL 的 WHERE 條件**（讓查詢本身只在條件成立時回傳列），而不是查全部列再逐欄比對——因為 ARTF runtime 沒有後者的能力。`docs/02-architecture/06_artifact_contracts.md:777` 提到的 `db_field_equals` verify type 在文件的核心分類表裡列出，但**[JAVA]** 沒找到任何實作（`grep -rn "db_field_equals" src/main/java/` 無結果）——這也是契約領先實作的例子。

**JSON/檔案層級的 ignore 機制**（跟 DB 無關，但回答「有無忽略機制」這問題的另一半）：`json_match` verify type**有**成熟的忽略機制，**[JAVA]** `CommonVerifyService.java:232-262` `evaluateJsonMatch`：`options.ignore_paths`（陣列，逐路徑從 expected/actual 兩邊都移除後再比對，line 235-237 `comparableJson`）+ `options.ignore_order`（陣列視為 set/排序後比對）+ `options.normalize`。範例：`samples/00-getting-started/golden_e2e/test_case.yaml:62-65` 的 `ignore_paths: [$.generatedAt]`。另一個實作版本 `WireMockHttpRequestCapabilityService.java:568-592` 的 `jsonMatches`/`removePath` 用的是點分隔路徑（`a.b.c`）而非 JSONPath `$.a.b.c`——**[推論] 兩個 json_match 實作對 ignore_paths 的路徑語法不一致**（CommonVerifyService 用 `$.` 開頭 JSONPath 風格，WireMockHttpRequestCapabilityService 用純點分隔），CaseSmith 若要產生 ignore_paths，需要先確認目標 test case 會被哪個 verify engine 執行到。

---

## Q6. suite_manifest / environment_binding / env_profile

**suite_manifest 登錄 case 的方式**（`schemas/suite_manifest.v0.2.schema.yaml`）——兩種模型：

1. **leaf suite**（`suite_model.suite`，line 16-43）：`tests: [<test_case.yaml 相對路徑>, ...]`（`samples/00-getting-started/golden_e2e/suite_manifest.yaml:8-9`）。必填 `suite_id`, `selection`；選填 `profile`, `tests`, `artifact_roots`。**所有 tests[] 條目共用同一個 profile**（CLI `--profile` 或 `suite_manifest.profile`），單一 test case **不可**各自選不同 profile（`schemas/suite_manifest.v0.2.schema.yaml:29` `Individual test cases must not select a different runtime profile`）。
2. **suite group / child_suite_aggregation**（line 44-72）：`child_suites: [{id, ref, profile, expected_status}]`，用來聚合多個子 suite manifest（`samples/20-provider-capability-p0/suite_manifest.yaml:5-53` 是典型範例，聚合 12 個 provider capability 子 suite）。這是「相容聚合」模型，不是主要 runner 模型（`purpose: Compatibility aggregation ... this is not the primary multi-test runner model`，line 44-46）。

**artifact_roots**（`schemas/suite_manifest.v0.2.schema.yaml:31-43`）：canonical 必要根目錄 `provider_instances/`, `env_profiles/`；選填資料根 `fixtures`, `expected_results`, `queries`, `actual_samples`；**已棄用**根目錄 `execution_profiles`, `environment_bindings`（`authoring_rule: New v0.2.7 samples must not declare artifact_roots.execution_profiles or artifact_roots.environment_bindings`，line 43）。

**環境參數放哪一層**：**不放在 suite_manifest 或 DSL**，放在 **Env_Profile**（`schemas/env_profile.v0.2.schema.yaml`）。結構：`providers.<provider_id>.bindings.<binding_key>: <value|ref|secret_ref|generated_ref>`（line 43-59），連線字串/endpoint URL 一律走這層，DSL 和 Provider Instance 都**明文禁止**放 raw values（`provider_instance.v0.2.schema.yaml:44-45` `raw_urls_topics_db_strings_namespaces_credentials: prohibited`）。範例：`samples/00-getting-started/golden_e2e/env_profiles/local_golden.yaml:1-8`。

**產生器要不要一併產 suite_manifest**：**[推論]** 要。因為 `test_case.yaml` 本身不會被 runner 自動發現——`suite_manifest.yaml` 的 `tests[]` 是唯一的登錄點（`selection.mode: suite` 對應 `selection.suite: <name>`，CLI 用 `--suite <path>` 指到 suite_manifest.yaml，不是指到 test_case.yaml，見 `README.md:14-15` 的 quick start 指令）。CaseSmith 的 renderer 至少要能產生：`test_case.yaml` + `suite_manifest.yaml`（tests[] 指向它）+ `provider_instances/*.yaml` + `env_profiles/<profile>.yaml`，四者缺一跑不起來。

**environment_binding.v0.2 現況**：`schemas/environment_binding.v0.2.schema.yaml` 狀態仍標 `framework_owned_current_stage`（line 3），但已被 env_profile 取代（見 Q9）。samples 目錄下**查無**任何仍在用 `environment_bindings/` 根目錄的範例（已全部遷移到 `env_profiles/`，`CHANGELOG.md` 0.2.6 條目「Makes Env_Profile the canonical public runtime environment artifact for new samples」）。**CaseSmith 應該只針對 env_profile 出 renderer，不用管 execution_profile/environment_binding。**

---

## Q7. result / evidence 輸出報告形狀

**Result JSON**（`schemas/result.v0.2.schema.yaml`）：

必填頂層欄位（line 7-27）：`framework_version`, `dsl_version`, `suite_id`, `batch_id`, `run_id`, `test_case_id`, `test_count`, `status`, `profile`, `environment`, `start_time`, `end_time`, `duration_ms`, `timestamps`, `test_results`, `provider_results`, `steps`, `verify_results`, `evidence_refs`, `failure`。

供 eval 迴圈 parse 通過率的關鍵欄位：
- **suite 層級**：`status`（整體 passed/failed/blocked，隱含於 test_results 彙總）、`test_count`（= `test_results.length`，line 64 明文要求相等且必須是 JSON 整數非字串）
- **per-test 層級**：`test_results[]`，每筆必含 `test_case_id`, `status`, `profile`（line 67）；`status` 允許值 `passed`, `failed`, `blocked`（line 68）
- **per-provider 層級**：`provider_results[]`，必含 `provider_id`, `provider_type`, `profile`, `runtime_mode`, `resolved_operation_result`, `release_evidence_eligible`（line 81-86）——`release_evidence_eligible` 這個布林值標示該次執行是否可作為「下游 release 證據」（mock/local 跑法通常是 `false`，如 `samples/00-getting-started/golden_e2e/result/expected_result_shape.json:60`）
- **per-verify-check 層級**：`verify_results[]`，範例形狀 `{id, type, status, diff_ref?}`（`samples/00-getting-started/golden_e2e/result/expected_result_shape.json:107-119`）
- **失敗資訊**：`failure: {code, classification, reason, owner_action}`，全部欄位在 pass 時為 `null`（同檔 line 140-145）

具體 JSON 範例：`samples/00-getting-started/golden_e2e/result/expected_result_shape.json`（單 provider）、`samples/10-contract-baseline/mixed_wiremock_jdbc_nats/result/sample_result.json`（多 provider，展示 `provider_summary[]` + `provider_results[]` 陣列如何對應多個 target）。

**多 provider 規則**（`schemas/result.v0.2.schema.yaml:73` + `:77-78`）：多 provider 結果必須用 `provider_summary[]`／`provider_results[]`，不可用第一個 provider 的 top-level 欄位代表整個 suite；`provider_evidence_refs[]` 不可混入 framework log/batch summary/assertion diff/expected artifact（這些只能出現在 `evidence_refs[]`）。

**Evidence Index**（`schemas/evidence_index.v0.2.schema.yaml`）：`entries[]` 每筆必含 `evidence_id`, `evidence_type`, `produced_by`, `test_case_id`, `run_id`, `batch_id`, `file_path`, `content_type`, `status`, `created_at`, `masking_applied`, `linked_result_field`（line 10-22）；provider 產出的 entry 額外必含 `provider_type`, `provider_id`（line 23-25）。`evidence_type` 允許值枚舉在 line 26-38：`execution_log`, `batch_summary`, `fixture_setup`, `fixture_cleanup`, `wiremock_request_journal`, `wiremock_server_log`, `jdbc_seed`, `jdbc_query`, `jdbc_cleanup`, `nats_event`, `assertion_diff`, `polling_observation`。範例：`samples/00-getting-started/golden_e2e/evidence/expected_evidence_index.yaml`。

**[推論]** eval 迴圈要算通過率，讀 `result.json` 的 `test_results[].status`（單一 test case 的情況直接讀最外層 `status`）即可，不需要解析 evidence_index；evidence_index 是拿來追溯個別 evidence 檔案存不存在／有沒有被遮罩（`masking.raw_secret_found`，`schemas/evidence_index.v0.2.schema.yaml` 對應各 sample 檔案的 `masking:` 區塊）。

---

## Q8. samples/ 完整可跑範例清單

依複雜度排序：

| 路徑 | 說明 | provider 數 |
|---|---|---|
| `samples/00-getting-started/golden_e2e/` | 最小可執行生命週期範例（`sample_fake_provider`，不連真實系統） | 1 |
| `samples/10-contract-baseline/mixed_wiremock_jdbc_nats/` | 混合 WireMock + JDBC(Oracle) + NATS，最貼近「seed DB → 跑程式 → 送 API request → 比對 DB + 攔截 request」的完整模型 | 3 |
| `samples/20-provider-capability-p0/data/jdbc/` | 純 JDBC CRUD（Oracle/DB2 雙方言），含 `test_case_db2_crud.yaml`, `test_case_oracle_crud.yaml`, 外部連線變體 `test_case_external_db2_crud.yaml`/`test_case_external_oracle_crud.yaml` | 1 |
| `samples/20-provider-capability-p0/http/wiremock_http_mock/` | 純 WireMock mock + request body 全等比對範例（`http_mock_request_body_match`） | 1 |
| `samples/20-provider-capability-p0/http/rest_client_with_wiremock/` | `rest_client` 打真實 HTTP 到 WireMock，含 boundary/failure 變體 | 2 |
| `samples/20-provider-capability-p0/messaging/{kafka,ibm_mq,nats,kafka_ibm_mq_mixed}/` | 訊息類 provider 各自範例 | 1-2 |
| `samples/20-provider-capability-p0/rpc/{grpc_mock,soap_mock}/` | gRPC/SOAP mock，含 boundary/failure 變體 | 2 |
| `samples/20-provider-capability-p0/verification/{artifact_compare,common_verify,polling_observer}/` | 純驗證類 provider（不跑外部系統，只比對既有 artifact） | 1 |
| `samples/30-cross-provider-groups/mock_server_cross_verify/` | suite group，聚合 6 個 REST/SOAP/gRPC 子 suite（含正反案例） | 多 |
| `samples/40-evidence-reporting/evidence_hardening/` | result/evidence 驗證用的固定 fixture（含 invalid 案例） | N/A |
| `samples/90-compatibility/dummy_rest/` | 相容性用途 fixture，非受支援 provider capability gate（`samples/README.md:12`） | 1 |

**建議 CaseSmith 對照的黃金範例**：`samples/10-contract-baseline/mixed_wiremock_jdbc_nats/`（涵蓋 DB seed/query/cleanup + HTTP mock 攔截 + 事件發布，最貼近 CaseSmith「seed DB → 跑 .exe → 送 API → 比對 DB+request」的模型，只差一個 `shell_command`/`external_runner` 跑 .exe 的步驟——這個模型目前 ARTF samples 裡**查無**現成範例，三個 runner provider_type 在 `docs/02-architecture/contracts/provider-contracts/` 下只有契約定義，`samples/` 底下**沒有**任何 test_case 使用 `shell_command`/`vm_runtime`/`external_runner`）。

---

## Q9. 版本註記

- **[SCHEMA]** 所有 9 份 schema 檔案 `contract_version`/`schema_version` 皆為 `v0.2`，`version_compatibility.supported_versions: [v0.2]`，`unsupported_version_behavior` 一致為 `block_before_execution` 或 `block_before_provider_dispatch`——即目前**只有 v0.2 是可執行版本**。
- **v1 相容性**：只有 `test_case_dsl.v0.2.schema.yaml:6-8` 提到 `legacy_read_versions: [v1]`，且明文 `legacy_promotion_behavior: legacy artifacts may be read only through explicit compatibility translation and must not be written as new v0.2 artifacts`——**CaseSmith 的 renderer 不應該輸出任何 v1 相容欄位**，只需針對 v0.2 出。其餘 8 份 schema **查無** v1 相容宣告（沒有 `legacy_read_versions` 欄位）。
- **舊欄位名清單**（`docs/02-architecture/06_artifact_contracts.md:670-680` 表格 + `schemas/test_case_dsl.v0.2.schema.yaml:97-118` prohibited_sections）需要避開：`execution_target`, `target_ru_id`, `call_ru`, `package_inputs`, `oracles`, `steps`, `assertions`, `evidence_required`, `policy`, `rp_id`, `ac_id`, `data_binding`, `datasets`, `fixtures`, `expected_results`, `db_seed`, `db_cleanup`, `mock_stubs`, `approval_status`, `waiver`, `release_gate`, `risk_approval`, `scenario`。
- **內部版本演進但契約版本不變**：`env_profile.v0.2.schema.yaml` 的 `status: framework_owned_next_interface` + `compatibility.replaces_public_artifacts: [execution_profile.v0.2.schema.yaml, environment_binding.v0.2.schema.yaml]`（line 13-16）——這三份雖然都叫 `v0.2`，但 `env_profile` 是**新的**、`execution_profile`/`environment_binding` 是**被取代但仍作為 runtime 相容輸入**（`old_artifacts_remain_runtime_compatibility_inputs: true`）。`samples/README.md:18` 明文：「New samples must not include `execution_profiles/`, `environment_bindings/`...」。**CaseSmith 只需要實作 env_profile 的 renderer，不用管另外兩份**，即使它們的 schema 檔案狀態仍標示 `framework_owned_current_stage`（容易誤判為「現行」，實際上已被取代）。
- **框架 release 版本**（與契約版本是兩件事）：`CHANGELOG.md` 顯示目前 framework 到 `0.2.7`（`CHANGELOG.md:3`），逐版都強調「DSL and contract artifacts remain at public contract version v0.2」（各版本 Known boundaries 區塊）——即 framework 本身持續迭代，但公開契約版本號自 v0.2 起沒有變過。
- **provider_type 別名棄用**：`kafka_messaging` 是 `kafka` 的棄用相容別名（`docs/01-specs/03_feature_specs.md:441`：「`kafka` is the canonical Kafka provider type for new artifacts. Existing `kafka_messaging` is a deprecated compatibility alias」）——CaseSmith 若產生 Kafka 相關 provider_instance，應該用 `kafka`，不要用 `kafka_messaging`。

---

## 總結給另一個 agent 的關鍵事實（供直接引用）

1. **test_case_dsl 頂層骨架**必填：`dsl_version, test_case_id, status, revision, targets, execute, verify, evidence, runtime`；`setup`/`cleanup`/`data` 條件必填。禁止出現 `fixtures`, `sql`, `mock_mapping`, `steps`, `assertions` 等舊欄位名。
2. **Seed 引用**：DSL 只能用 `data.<name>.ref` 間接指到 checked-in 檔案（SQL 純文字檔 / WireMock stub JSON / payload JSON），SQL 執行由 `JdbcProviderRuntime`（Java）做，DSL 本身不含 SQL。沒有「base fixture + per-case 增量」的框架級機制，需要 planner 自己組。
3. **跑 .exe**：走 `shell_command`（或 `vm_runtime`/`external_runner`）provider_type 的 `execute_command`/`run_batch` operation，`runner.args.*` 帶參數、`runner.env.*` 帶環境變數；**查無工作目錄欄位**；跑任意指令預設被 `safety.access_policy` 閘門擋住，需顯式核准。ARTF samples 裡**沒有**這類 provider 的可跑範例可抄。
4. **mock request 比對**：`send_http_request` 算 matched_count 只比 method+path（不比 body）；`http_mock_request_body_match` verify type 對 body 做**完全相等**比對（Java Map.equals），無部分匹配、無欄位排除機制。`mock.body_pattern` 契約有宣告但**未實作**。
5. **DB snapshot 比對**：不是全表/全列比對，是 `row_count`/`matched`（存在性）比對；最多存 5 列樣本僅供證據參考，不參與判定；無欄位級 ignore 機制。要驗證精確欄位值必須把條件寫進 SQL WHERE，不能查全部再比對。
6. **suite_manifest 登錄**：`tests: [<test_case.yaml path>]`，同 suite 內所有 test 共用一個 profile；環境值（連線字串/endpoint）一律放 `env_profile.providers.<id>.bindings`，DSL/Provider Instance 都禁止塞 raw 值。CaseSmith renderer 最少要出 4 種檔案：test_case.yaml + suite_manifest.yaml + provider_instances/*.yaml + env_profiles/*.yaml。
7. **Result JSON** 的 `test_results[].status`（passed/failed/blocked）是 eval 迴圈算通過率的主要欄位；多 provider 必用 `provider_summary[]`/`provider_results[]` 陣列，不可用單一 top-level 欄位代表整個 suite。
8. 黃金參考範例：`samples/10-contract-baseline/mixed_wiremock_jdbc_nats/`（DB+HTTP mock+事件三合一，最接近 CaseSmith 目標模型，但缺一個跑 .exe 的 provider 範例）。
9. **只做 v0.2**，避開所有 legacy/prohibited 欄位名；env_profile 是唯一該實作的環境層 renderer（execution_profile/environment_binding 已被取代，即使 schema 檔案狀態欄位還寫 current_stage）。
