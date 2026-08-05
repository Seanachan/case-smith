# 需求:block 層級的行為追蹤(2026-08-05,使用者口述)

## 需求原文(整理)

- 輸入單位是一個 **block**(一段業務描述),不是單一方法。
- block 內含大量**跨表操作**;事前**不知道**它會用到哪些 schema、表、服務。
- 只知道 block 在做什麼、會執行哪類操作。
- 因此 extractor 要**追蹤原始碼行為**:順著呼叫鏈往下,找出實際用到的
  schema/表/服務(gRPC、HTTP API…)以及**怎麼用**。
- schema 不必然只有一份——系統比目前的 example 配置複雜。

## 現有架構已涵蓋(不用動)

| 能力 | 位置 | 說明 |
|---|---|---|
| 多表 seed | `SeedPlanner.plan_base(tables)` | 吃表清單,FK 閉包自己算 |
| 多 schema 資料模型 | `Table.schema_name`(schema JSON 的 `"schema"` 欄) | 一份 JSON 可裝多 schema 的表 |
| 下游解耦 | planner/orchestrator/renderer | 只吃「表清單+欄位白名單」,不管上游怎麼發現 |

## 缺口(要做)

1. **Extractor v2:呼叫鏈閉包**(最大塊,extractor 那條線)
   - v1 是 per-method syntax-level,明文不做跨方法資料流。
   - 需要:block 進入點 → 呼叫圖 transitive closure → 聯集底下所有
     tables/operations/condition_columns/endpoints → 吐 block 層級的 spec card。
   - spec card 契約要加:block 定義(進入點集合)+ 聚合結果;
     per-method 明細保留(除錯用)。
2. **SQL 的 schema 前綴**:`emit_sql` / verify SQL 目前吐裸表名;
   多 schema 時要 `SCHEMA.TABLE` 限定(`Table.schema_name` 已有,只是沒用上)。
   跨 schema 同名表:planner 以表名為 key,會撞——key 要改 qualified name。
3. **服務類 provider**:extractor 的 EndpointAnalyzer 只認 HTTP;gRPC 呼叫點
   偵測未做。renderer 目前只出 jdbc provider;之後要出 wiremock_http_mock /
   grpc_mock 的 provider_instance + stub + verify(ARTF 有對應 provider,
   body 比對是全等——見 ARTF_CONTRACT.md Q4)。

## block 邊界(2026-08-05 已定案)

使用者給**半結構化描述檔**(block.yaml),兩種輸入、兩種用途:

```yaml
block_id: OrderSettlement
description: >
  自然語言行為描述——給人/報告/few-shot 語意脈絡,不進結構決策(鐵律)。
anchors:            # 呼叫圖起點,「不用齊全」是特性:漏的靠 closure 補
  - function: SettleOrder          # 函式名(可帶 namespace 前綴)
  - file: Billing/Settle.vb        # 或 檔案 + 行號範圍
    lines: 120-180                 # 行號 → 所屬方法:spec card 已有 file+line,查表即得
```

- extractor 從 anchors 起跳做呼叫圖 transitive closure,聯集表/操作/條件欄/endpoint。
- **coverage 報告是驗收機制**:extractor 吐「實際碰到的表(操作)+ endpoint」
  清單,人對照 description 找落差(描述錯 / 錨點漏,在這裡現形,早於假綠測試)。

## 輸入現實(2026-08-05 補充)

- 使用者手上實際是**一批描述 block 行為的 markdown 檔**,不是 block.yaml。
- 流程定為:`block.md →(開發期強模型 + 人審,一次性)→ block.yaml 錨點`。
  NL→錨點的對應由強模型做,**合規**——7–8B 限制只套執行期(HANDOFF §1)。
- md 沒提函式名時:拿 md 關鍵詞對 spec card 方法清單做候選建議,人挑。
- markdown 維持 source of truth;coverage 報告對照對象就是它。

## 範圍裁剪

- **gRPC 暫不測**(2026-08-05 使用者裁定)→ 缺口 3 縮為 HTTP only,
  `.proto` 問題消失。gRPC 標 future work。

## 執行拓撲(2026-08-05 裁定)

- 查證:ARTF 三種 runner provider(shell_command / vm_runtime / external_runner)
  在 0.2.7 全為 **contract_only**(support matrix 明寫;Java 端無真執行)——
  HANDOFF §4「執行模型」假設框架跑 .exe,原本不成立。
- 裁定:**使用者正在 ARTF 內實作 shell_command runtime**(框架是使用者的)。
  CaseSmith 不做兩段式指揮 workaround。
- CaseSmith 側先備齊:假 SUT(`sut/FakeSut.java`,Java+jcc 替身;真 SUT 是
  VB .exe 在公司側)、renderer 的 shell_command target(照契約離線先行)。
- Golden master 流程(runtime 落地後):seed → 框架跑 SUT → 從 db_query
  evidence(sample_rows ≤5)抓現況 → 以觀測值重生 verify SQL。

## 待使用者釐清

- 跨 schema 有沒有 FK(影響閉包要不要跨 schema 走)?
