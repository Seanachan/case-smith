# CORPORATE_SETUP — 在 corporate device 上架環境

目標：把這個 repo 搬到有真實 VB.NET 專案、DB2、ARTF framework、7–8B 模型的機器上，
架起環境並確認能重現本機（Mac，2026-08-05）已驗證過的測試結果。唯一事實來源仍是
[`HANDOFF.md`](./HANDOFF.md)／[`CONTRACTS.md`](./CONTRACTS.md)；本檔與它們衝突時
以它們為準。

## 前置需求

| 工具 | 版本／取得方式 | 檢查指令 |
|---|---|---|
| Python | 3.13。優先 `uv sync`（`pyproject.toml` 已定依賴）；沒有 uv 時 `pip install -r requirements.txt`（repo 根已附，`uv export` 自動產生） | `python3 --version` |
| .NET SDK | 9（本機已驗證 `9.0.101`）。優先裝本機 SDK；沒有時用 Docker 備援 `extractors/dotnet/Dockerfile`（`mcr.microsoft.com/dotnet/sdk:9.0`） | `dotnet --version` |
| Java | 跑 ARTF framework 用。`docs/USAGE.md` 記載 ARTF 自己的「5-Minute Quick Start」要求 **Java 17+**；精確版本以 framework repo（<https://github.com/Seanachan/Auto_Regression_Test_Framework>）的 `pom.xml` 為準，**不要憑印象猜** | `java -version` |

## 取得程式碼

傳輸方式待定（git remote push/pull、`git bundle`、或整包 zip，三選一，主線之後補）。

> 目前本機 repo 領先 `origin/main` 5 個 commit，且有尚未 commit 的異動（多個平行
> session 產出的檔案，例如 `pipeline/trust_gate.py`、`extractors/dotnet/
> CaseSmith.Extractor/` 等仍是 untracked）。打包前先確認要不要先 commit，避免
> 漏帶檔案；`git status` 是最後一道檢查。

## 驗證安裝

在 repo 根目錄依序跑，指令與順序照 `docs/USAGE.md`「測試」節：

```bash
uv run pytest pipeline/ -q
uv run python -m unittest discover -s orchestrator/tests -t .
cd extractors/dotnet && dotnet test
```

本機（2026-08-05）實跑的預期結尾，作為比對基準：

1. `uv run pytest pipeline/ -q` → `93 passed in 0.20s`
   （涵蓋 `test_cli`／`test_e2e_fake`／`test_flaky_gate`／`test_render_contract`／
   `test_seed_planner`／`test_trust_gate` 六個檔；`HANDOFF.md` §5 目前只記到
   `test_seed_planner.py` 55 tests，其餘是後續平行工作的產物，尚未補進 §5——
   **數字以實跑為準，不是以 HANDOFF 文字為準**。）
2. `uv run python -m unittest discover -s orchestrator/tests -t .` →
   `Ran 25 tests in 0.004s` / `OK`
3. `cd extractors/dotnet && dotnet test` → 兩個測試專案分別
   `CaseSmith.Mutator.Tests`：8 通過、`CaseSmith.Extractor.Tests`：14 通過（合計 22）。
   本機是中文 locale，顯示「已通過！」；公司機器 locale 不同可能顯示英文
   `Passed!`，看**通過數字**即可，不用管語言。

若公司機器的數字（尤其 pytest 那條）跟這裡不同，先比對是不是這台機器的 repo
版本落後於帶過去的版本，不要預設是環境設定問題。

## 部署後第一批工作

對應 `HANDOFF.md` §6 剩餘工作，依序：

1. **`.mjs` 對齊 schema 契約**：把公司 DB2 export 的 `.mjs` parse script 輸出，改到
   符合 `schema/schema.example.json` 的形狀（或評估反過來改 `Schema.from_json`
   遷就它，看哪邊改動小）。若 `INTAKE_CHECKLIST.md` 帶回的 DDL 樣本裡有複合 FK，
   要先補這段（`CONTRACTS.md` 記錄的已知限制）再往下走。
2. **extractor 掃真 VB**：
   `dotnet run --project CaseSmith.Extractor -- --input <真專案目錄> --output spec.json`，
   輸出對照 `CONTRACTS.md`「spec card 契約」人工抽查幾筆。
3. **planner 接真 schema 跑**：拿真 schema 資料替換掉 `test_seed_planner.py` 裡的
   example schema 再驗一輪，確認 FK 閉包／拓撲排序沒有意外 raise。
4. **framework 亂序 3 次實跑餵 trust_gate**：這一步需要 Java＋DB2 環境，本機只能把
   harness 備好（`python -m pipeline.trust_gate {shuffle,compare}`），沒辦法在本機
   跑完整流程——公司環境是第一次真正跑這條路徑。
5. **mutant 殺傷率**：`extractors/dotnet/CaseSmith.Mutator` 產生 mutant 之後，交給
   ARTF suite 重新 build＋run 並統計殺傷率；這一步是使用者側 framework 的事，
   CaseSmith 只負責出 mutant，不負責跑。

## transport 換裝

`opencode` CLI（目前唯一實作的 transport）需要登入、走網路，公司內部大概率沒有。
好消息是 orchestrator 把模型呼叫收在一個可插拔的 `ModelClient` protocol
（`orchestrator/client.py`）——新 transport 只需要實作「吃一個 prompt 字串、回一個
字串」這一個方法，參考現成的 `FakeClient`（測試用，不打網路）與 `OpencodeClient`
（真實 shell-out 範例）兩種寫法即可。等 `INTAKE_CHECKLIST.md` 第「模型 serving」項
（runtime／API 形狀／模型名）到位再動手寫，先別猜 API 形狀。

## 紅線

真實 schema／表名／連線字串**不出 corporate device**。`.gitignore` 已擋
`domain/*.yaml`、`schema/*.json`、`schema/*.ddl`（`.example.*` 除外）；但這只保護
「進這個 repo 的檔案」，帶回來的 markdown、`.mjs` 產生的中間輸出、貼進去的 request
樣本都不受這條規則保護，進 repo 前一律要先過一輪去敏感化（見
`INTAKE_CHECKLIST.md`「去敏感化」節）。
