# CaseSmith

用 7–8B 小模型為 legacy 專案（目前支援 VB.NET，架構預留 Java 擴展）產生可信賴的回歸測試。

核心設計原則：**能用確定性程式碼做到的，絕不寫成給模型的指示。** 小模型的可靠度來自
結構性保證，不是來自 prompt——模型只負責填語意值，不決定表的順序、FK 值、命名慣例
或輸出格式；這些一律由 Python 端的 planner / renderer / orchestrator 決定。細節見
[CLAUDE.md](./CLAUDE.md)。

## 架構

```
extractors/
  dotnet/        C#／Roslyn extractor，吐語言無關的 spec.json（骨架，尚未實作；Docker 跑 dotnet）
  jvm/           規劃中，尚未建立目錄——未來 Java 支援走這裡
pipeline/        Python：seed planner——schema model／FK 傳遞閉包／拓撲排序／
                 domain 三層 fallback／ID 配號／SQL 輸出
orchestrator/    Python：prompt 組裝／opencode CLI transport／失敗分類重試／量測
domain/          domain.yaml——跨專案時唯一要改的地方（真實檔案不進版控）
schema/          schema.json 契約 + DDL 範例（真實檔案不進版控）
skill/           規劃中，尚未建立目錄——SKILL.md 及模型 prompt 範本最終會放這裡
                 （目前範本暫在 orchestrator/templates/）
docs/            架構、介面契約、交接文件
```

> 這棵樹是目前實際的 repo 佈局。`CLAUDE.md`〈架構〉節描述的是目標形狀（orchestrator
> 併在 pipeline/ 下、範本放 skill/）；`orchestrator/` 因為是平行 session 重建，目前是
> 獨立的頂層目錄，範本也還留在 `orchestrator/templates/`。等 orchestrator 接上
> planner（見 docs/HANDOFF.md §6）後再考慮要不要搬。

**關鍵解耦**：`schema/schema.example.json` 的格式是語言無關的。新增語言（如 Java）
只需要新的 extractor 吐同樣形狀的 spec，下游 pipeline / orchestrator 不用改。

## Quickstart

Planner 測試（純 Python，無外部依賴）：

```bash
uv run python -m pytest pipeline/test_seed_planner.py
```

Orchestrator 測試（零第三方依賴，`FakeClient` 不打網路）：

```bash
uv run python -m unittest discover -s orchestrator/tests -t .
```

dotnet extractor（骨架階段，尚無 .sln 可建；Mac 上一律走 Docker，不裝本機 SDK）：

```bash
docker run --rm -v "$PWD":/src -w /src mcr.microsoft.com/dotnet/sdk:9.0 dotnet build
```

指令與版本見 `extractors/dotnet/README.md`。

## 文件

- [`CLAUDE.md`](./CLAUDE.md)——設計原則、已定案決定、注意事項
- [`docs/HANDOFF.md`](./docs/HANDOFF.md)——現況、已做的架構決定、優先序（唯一事實來源）
- [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md)——端到端資料流、執行模型、元件職責
- [`docs/CONTRACTS.md`](./docs/CONTRACTS.md)——schema JSON／domain.yaml／ModelSlot／
  SeedPlanner API 等介面規格

## 注意事項

真實 schema、表名、連線字串**不進版控**。`domain/*.yaml` 與 `schema/*.json`／`*.ddl`
已在 `.gitignore`；只有 `*.example.*`（假名、非任何真實系統）進版控。
