# CaseSmith

用 7–8B 小模型為 legacy 專案（目前支援 VB.NET，架構預留 Java 擴展）產生可信賴的回歸測試。

核心設計原則：**能用確定性程式碼做到的，絕不寫成給模型的指示。** 小模型的可靠度來自
結構性保證，不是來自 prompt——模型只負責填語意值，不決定表的順序、FK 值、命名慣例
或輸出格式；這些一律由 Python 端的 planner / renderer / orchestrator 決定。細節見
[CLAUDE.md](./CLAUDE.md)。

## 架構

```
extractors/
  dotnet/        C#／Roslyn，兩個獨立專案：
                   CaseSmith.Extractor   VB 原始碼 → spec.json（v1.1，syntax-level）
                   CaseSmith.Mutator     VB 原始碼 → mutant 樹 + manifest.json（測試品質篩選閘）
  jvm/           規劃中，尚未建立目錄——未來 Java 支援走這裡
pipeline/        Python：
                   seed_planner.py      schema model／FK 傳遞閉包／拓撲排序／
                                        domain 三層 fallback／ID 配號／SQL 輸出
                   render_artifacts.py  ARTF v0.2 四種檔 renderer（含 ignore_in_snapshot
                                        落地於 verify SQL）
                   contract_check.py    renderer 輸出的契約檢查
                   cli.py               conductor：spec+schema → bundle，一條指令跑完
                   flaky_gate.py        亂序多輪結果判定器（stable／flaky／blocked／missing）
                   trust_gate.py        亂序洗牌器（確定性 seed，判定另外交給 flaky_gate）
orchestrator/    Python：prompt 組裝／opencode CLI transport／失敗分類重試／量測
domain/          domain.yaml——跨專案時唯一要改的地方（真實檔案不進版控）
schema/          schema.json 契約 + DDL 範例（真實檔案不進版控）
skill/           規劃中，尚未建立目錄——SKILL.md 及模型 prompt 範本最終會放這裡
                 （目前範本暫在 orchestrator/templates/）
docs/            架構、介面契約、交接文件（索引見下）
```

**關鍵解耦**：`schema/schema.example.json` 的格式是語言無關的。新增語言（如 Java）
只需要新的 extractor 吐同樣形狀的 spec，下游 pipeline / orchestrator 不用改。

## Quickstart

三條測試指令（改完任何元件都跑這三條；數字是 2026-08-05 的基準）：

```bash
uv run pytest pipeline/ -q                                     # 86 passed
uv run python -m unittest discover -s orchestrator/tests -t .  # 25 OK
cd extractors/dotnet && dotnet test                             # 22（Extractor 14 + Mutator 8）
```

一鍵端到端 smoke（全假件，spec+schema → ARTF bundle）：

```bash
uv run python scripts/e2e_smoke.py --model opencode/big-pickle --out out/run1
```

指令與版本細節見 `extractors/dotnet/README.md`、完整操作流程見 `docs/USAGE.md`。

## 目前進度

**機器側（Mac 開發機）已完成：**

- seed planner 定案（FK 閉包／拓撲排序／domain 三層 fallback／hints 詞彙表／ID 配號／emit_sql）
- renderer + 契約檢查 + conductor CLI（ARTF v0.2 四種檔，`ignore_in_snapshot` 落地於 verify SQL）
- 信任閘門三項全部落地：verify SQL 欄位排除、洗牌器（trust_gate）+ 判定器（flaky_gate）、
  mutation injector（CaseSmith.Mutator，三類運算子）
- extractor v1.1（CaseSmith.Extractor，syntax-level 抽取）
- orchestrator 接線：`ModelSlot` 正本裁決在 `pipeline/seed_planner.py`，orchestrator 直接
  import；opencode CLI transport 跑通
- E2E smoke 已用真模型（`opencode/big-pickle`）＋真 DB2 跑通 3 輪全綠，flaky_gate 判定
  `STABLE passed`，bundle 契約零違規（見 `docs/USAGE.md`「實測狀態」）

**待使用者環境（公司側）：**

- 接真實 schema（目前 `.mjs` 對齊已降為 future work，E2E 全走 `schema/schema.example.json` 假件）
- 對真實 VB.NET 專案跑 extractor（目前只有 fixture 假 VB 檔）
- ARTF 三次亂序在使用者側 Java + DB2 環境實跑（本機已用 Docker DB2 驗證流程，非使用者真環境）
- extractor v2：block 呼叫鏈閉包（缺口分析見 `docs/REQ_BLOCK_TRACING.md`）
- block.md → block.yaml 錨點轉換（開發期強模型 + 人審，一次性）

詳細狀態與優先序見 `docs/HANDOFF.md`（唯一事實來源）。

## 文件

- [`CLAUDE.md`](./CLAUDE.md)——設計原則、已定案決定、注意事項
- [`docs/HANDOFF.md`](./docs/HANDOFF.md)——現況、已做的架構決定、優先序（唯一事實來源）
- [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md)——端到端資料流、執行模型、元件職責
- [`docs/CONTRACTS.md`](./docs/CONTRACTS.md)——schema JSON／domain.yaml／ModelSlot／
  SeedPlanner API／spec card 等介面規格（釘介面用，改動需同步程式碼）
- [`docs/ARTF_CONTRACT.md`](./docs/ARTF_CONTRACT.md)——ARTF（目標測試框架）v0.2 契約抽取
  報告，逐題附 file:line 出處
- [`docs/USAGE.md`](./docs/USAGE.md)——從 VB 原始碼到 ARTF bundle 的完整操作 SOP，含實測狀態
- [`docs/REQ_BLOCK_TRACING.md`](./docs/REQ_BLOCK_TRACING.md)——block 層級行為追蹤需求：
  block.yaml 輸入格式定案 + extractor v2（呼叫鏈閉包）缺口分析
- [`docs/INTAKE_CHECKLIST.md`](./docs/INTAKE_CHECKLIST.md)——使用者帶回真實系統 markdown
  時要涵蓋的欄位檢核表
- [`docs/CORPORATE_SETUP.md`](./docs/CORPORATE_SETUP.md)——把 repo 搬到公司側真實環境時的
  架設步驟，目標是重現本機已驗證的測試結果

## 注意事項

真實 schema、表名、連線字串**不進版控**。`domain/*.yaml` 與 `schema/*.json`／`*.ddl`
已在 `.gitignore`；只有 `*.example.*`（假名、非任何真實系統）進版控。
