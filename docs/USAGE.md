# CaseSmith 操作 SOP

從 VB.NET 原始碼到 ARTF 可執行 test bundle 的完整流程。

> **ARTF** = Auto Regression Test Framework,即目標測試框架
> https://github.com/Seanachan/Auto_Regression_Test_Framework(Java/Spring Boot)。
> CaseSmith 產生的 bundle 就是餵給它跑的。契約查證報告見 `docs/ARTF_CONTRACT.md`。
每一步都可獨立跑;沒有真專案/真 schema 時,全流程可用 example 假件走通(§5 一鍵版)。

```
VB 原始碼 ──①extractor──▶ spec.json ─┐
DB2 DDL ───②ddl2json────▶ schema.json ─┼─③planner──▶ SeedPlan + ModelSlot
                                        │                    │
domain.yaml(選填)──────────────────────┘         ④orchestrator(7–8B 模型填值)
                                                             │
                                              ⑤renderer──▶ ARTF v0.2 bundle
                                                             │
                                              ⑥ARTF runner(Java)──▶ result.json
```

## 0. 環境需求

| 工具 | 用途 | 檢查指令 |
|---|---|---|
| uv | Python 套件/環境管理 | `uv --version` |
| opencode CLI(已登入) | 模型呼叫 transport | `opencode models` |
| dotnet SDK 9 | extractor(本機優先;無 SDK 用 Docker 備援) | `dotnet --version` |

初次 clone 後:`uv sync`(裝 pyyaml + dev deps)。

## 總指揮 CLI:一條指令跑完 ③④⑤⑥

①②(spec.json、schema.json)備好之後,其餘全部交給 CLI:

```bash
uv run python -m pipeline.cli \
    --spec   extractors/spec_card.example.json \
    --schema schema/schema.example.json \
    --domain domain/domain.example.yaml \
    --method GetActiveCustomer \
    --model  opencode/big-pickle \
    --out    out/demo
```

### 參數表:放什麼、從哪來

| 參數 | 必填 | 放什麼 | 值從哪來 |
|---|---|---|---|
| `--spec` | ✔ | extractor 產的 spec card JSON **路徑** | 步驟①的 `--output`;沒真專案 → `extractors/spec_card.example.json` |
| `--schema` | ✔ | DB schema JSON **路徑** | 步驟②的 ddl2json 輸出;沒真 schema → `schema/schema.example.json` |
| `--method` | ✔ | 要產測試的**方法名**(如 `GetActiveCustomer`) | 先跑 `--list` 看 spec 裡有哪些;同名衝突時改用完整 id |
| `--domain` | 選 | domain config YAML 路徑 | 拿 `domain/domain.example.yaml` 改;控制欄位填充值 + `ignore_in_snapshot`。不給 = 空 config,型別預設值 |
| `--model` | 選 | opencode 的 `provider/model` 字串 | `opencode models` 列出可用名;預設 `opencode/big-pickle` |
| `--out` | 選 | 輸出**目錄** | 會產 `bundle/`(9 檔)+ `runs.jsonl`(量測);預設 `out/casesmith` |
| `--list` | 選 | (無值) | 只印方法清單(名稱、id、條件欄位)就結束 |
| `--fake` | 測試用 | 假模型回應 JSON 字串,如 `'{"T_CUSTOMER.COUNTRY_CD": "TW"}'` | 離線/CI 用,跳過真模型 |

CLI 自己做的事(你不用管):條件欄位過濾成 ask_model 白名單(PK/FK 排除
——ID 歸 planner 配)、FK 閉包、seed 順序、模型重試、契約檢查。
結尾印 `contract violations: none` = bundle 可交給 ARTF。

## ① Extractor:VB 原始碼 → spec.json

```bash
cd extractors/dotnet
dotnet build                      # 首次
dotnet run --project CaseSmith.Extractor -- \
    --input  /path/to/vb/project \
    --output spec.json
```

- `--input` 給**目錄**,遞迴掃底下所有 `*.vb`(不用 .sln,不需編譯)。
- 輸出 spec card JSON:每個方法的簽章、分支數、常數 SQL 抽出的表/欄、
  endpoint 呼叫點、`ask_model` 候選欄位。形狀見 `docs/CONTRACTS.md`,
  範例見 `extractors/spec_card.example.json`。
- 沒裝 dotnet:`docker run --rm -v "$PWD":/src -w /src mcr.microsoft.com/dotnet/sdk:9.0 dotnet run ...`(同參數)。

## ② Schema:DB2 DDL → schema.json

真 schema 由使用者側的 `ddl2json.mjs` 產;輸出必須對齊
`schema/schema.example.json` 的契約形狀(`Schema.from_json` 直接吃)。
沒有真 schema → 直接用 `schema/schema.example.json`(6 張假表)。

## ③+④+⑤ Pipeline:planner → 模型填值 → ARTF bundle

### 一鍵 smoke(全假件,驗證整條路)

```bash
uv run python scripts/e2e_smoke.py \
    --model opencode/big-pickle \
    --out   out/run1
```

產物:`out/run1/bundle/`(9 檔 ARTF v0.2 bundle)+ `out/run1/runs.jsonl`(量測)。
結尾印契約違規清單(`none` = 可交)。

### 分步 Python API(接真 spec/schema 時)

```python
import json
from pipeline.seed_planner import Schema, SeedPlanner, DomainConfig
from pipeline.render_artifacts import (
    CaseBundleSpec, render_bundle, verify_ignore_for, write_bundle,
)
from pipeline.contract_check import check_test_case, check_suite_manifest
from orchestrator import Orchestrator, OpencodeClient, MetricsLog
import yaml

# ③ planner:結構決策(表、順序、FK、ID)全在確定性程式碼
schema = Schema.from_json(json.load(open("schema/schema.example.json")))
domain = DomainConfig.from_yaml("domain/domain.example.yaml")   # 選填,空 config 也能跑
planner = SeedPlanner(schema, domain, ask_model=["T_ORDER.STATUS_CD"])  # 白名單來自 spec.json
base = planner.plan_base(["T_ORDER"])            # 目標表 → FK 閉包 → 共用 base fixture
row = planner.plan_case("T_ORDER", "Characterize_UpdateOrderStatus_Default")

# ④ orchestrator:模型只填 row.slots 標出的欄位
orch = Orchestrator(OpencodeClient(model="opencode/big-pickle"),
                    metrics=MetricsLog("out/runs.jsonl"))
result = orch.run_generate("Characterize_UpdateOrderStatus_Default",
                           method_context="<spec.json 的方法片段>", slots=row.slots)

# ⑤ renderer:值 → ARTF v0.2 bundle;欄位驗證釘進 verify SQL 的 WHERE
spec = CaseBundleSpec(case_id="Characterize_UpdateOrderStatus_Default",
                      title="...", suite_id="MY-SUITE")
files = render_bundle(spec, schema, base, row, result.values,
                      verify_ignore=verify_ignore_for(domain, schema, row.table))
write_bundle(files, "out/bundle")

# 交件前把兩份 YAML 過契約檢查(零違規才交)
assert check_test_case(yaml.safe_load(files[f"test_cases/{spec.case_id}.yaml"])) == []
assert check_suite_manifest(yaml.safe_load(files["suite_manifest.yaml"])) == []
```

失敗處理(orchestrator 自動分類,見 `orchestrator/README.md`):
SCHEMA → 自動重試 ≤2 次;SEMANTIC → 注入 few-shot 重試 1 次;
SQL_EXEC → 直接 raise `PlannerBugError`,**不要 retry,去修 planner**。

## ⑥ ARTF runner(Java 17+,指令出自 ARTF README「5-Minute Quick Start」)

```bash
# ARTF repo 內,首次:
./mvnw -DskipTests package

# 先讓框架自己驗 bundle(不執行,純契約檢查):
java -jar target/spec-driven-auto-regression-0.2.7.jar \
    validate --suite /path/to/bundle/suite_manifest.yaml

# 實跑:
java -jar target/spec-driven-auto-regression-0.2.7.jar \
    run --suite /path/to/bundle/suite_manifest.yaml --profile local_fake

# 報告:
java -jar target/spec-driven-auto-regression-0.2.7.jar \
    report --result <generated_result_json>
```

- runner 只認 suite_manifest(test_case.yaml 不會被自動發現)。
- 連線字串走 env_profile 的 `secret_ref: env://JDBC_CONNECTION` → 跑之前 export 該環境變數。
- 結果:`result.json` 的 `test_results[].status`(passed/failed/blocked)= eval 通過率來源;
  亂序多跑後丟給 `uv run python -m pipeline.flaky_gate <各次 result.json>` 篩 flaky。

### 實測狀態(2026-08-05,本機 ARTF 0.2.7 實跑)

- `validate`:CaseSmith bundle **passed,findings 零**(契約假設全數成立)。
- `run`:一路到 provider 層,卡在兩個環境前置(非 bundle 問題):
  1. `JDBC_CONNECTION` 環境變數(DB 連線字串)
  2. JDBC driver jar——框架不帶 driver,`doctor drivers` 確認 oracle/db2 皆缺;
     用 `--driver-path <jar>` / `REGRESS_DRIVER_PATH` / `usage-kit/drivers/` 提供。
- 真跑全綠還需要:一個 DB2(Docker)或相容 DB + 對應 driver jar。

## 測試(改完任何元件跑這兩條)

```bash
uv run pytest pipeline/ -q                                    # planner + renderer + 契約 + E2E
uv run python -m unittest discover -s orchestrator/tests -t .  # orchestrator
cd extractors/dotnet && dotnet test                            # extractor
```

## 常見錯誤對照

| 症狀 | 原因 | 修法 |
|---|---|---|
| `GenerationFailed: schema retries exhausted` | 模型吐不出合規扁平 JSON | 換模型/檢查 opencode 登入;長期解:constrained decoding |
| `PlannerBugError` | fixture SQL 在 DB 執行失敗 | 修 planner/schema,**retry 無效** |
| 契約違規 `prohibited section` | renderer 產出帶 legacy 欄位 | 回報 bug——renderer 硬編碼結構,不該發生 |
| `opencode exited 1` | CLI 未登入/模型名錯 | `opencode models` 列可用名,格式 `provider/model` |
