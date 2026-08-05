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

已定案（2026-08-05）：push 到 GitHub private repo
（`https://github.com/Seanachan/case-smith.git`），公司側 `git clone`。
前提是公司網路能到 github.com；不能的話 fallback 是 `git bundle` 單檔傳輸。
clone 完先 `git log --oneline -5` 對照本機,確認拿到的是最新 main。

## 驗證安裝

在 repo 根目錄依序跑，指令與順序照 `docs/USAGE.md`「測試」節：

```bash
uv run pytest pipeline/ -q
uv run python -m unittest discover -s orchestrator/tests -t .
cd extractors/dotnet && dotnet test
```

本機（2026-08-05）實跑的預期結尾，作為比對基準：

1. `uv run pytest pipeline/ -q` → `86 passed`
   （涵蓋 `test_cli`／`test_e2e_fake`／`test_flaky_gate`／`test_render_contract`／
   `test_seed_planner`／`test_trust_gate` 六個檔。**數字以實跑為準**;若公司側
   數字更高,通常是 main 又進了新測試,對 `git log` 即知。）
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
4. **block.md → block.yaml 錨點轉換**：帶回的 block markdown 由**開發期強模型＋人審**
   轉成 `block.yaml` 錨點（一次性;流程與格式見 `REQ_BLOCK_TRACING.md`）。7–8B 限制
   只套執行期,這步用強模型**合規**（HANDOFF §1）。
5. **framework 亂序 3 次實跑**：洗牌 `python -m pipeline.trust_gate shuffle`,跑完
   N 份 result 用 `python -m pipeline.flaky_gate run*/result.json` 判定
   （stable/flaky 踢除/blocked 人工）。這一步需要 Java＋DB2 環境,公司環境是
   第一次真正跑這條路徑。
6. **mutant 殺傷率**：`extractors/dotnet/CaseSmith.Mutator` 產生 mutant 之後，交給
   ARTF suite 重新 build＋run 並統計殺傷率；這一步是使用者側 framework 的事，
   CaseSmith 只負責出 mutant，不負責跑。

## transport

已確認（2026-08-05）：**公司內也用 opencode CLI**——現成的 `OpencodeClient`
直接用,只需換模型名（`opencode models` 列出可用清單）。不用寫新 transport。
若日後換 serving 方式:orchestrator 的 `ModelClient` protocol
（`orchestrator/client.py`）可插拔,新 client 只需實作「吃 prompt 字串、回字串」
一個方法,參考 `FakeClient` 與 `OpencodeClient` 兩種寫法。

## 紅線

真實 schema／表名／連線字串**不出 corporate device**。`.gitignore` 已擋
`domain/*.yaml`、`schema/*.json`、`schema/*.ddl`（`.example.*` 除外）；但這只保護
「進這個 repo 的檔案」，帶回來的 markdown、`.mjs` 產生的中間輸出、貼進去的 request
樣本都不受這條規則保護，進 repo 前一律要先過一輪去敏感化（見
`INTAKE_CHECKLIST.md`「去敏感化」節）。
