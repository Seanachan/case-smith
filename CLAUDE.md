# CaseSmith

用小模型（7–8B）為 legacy 專案產生可信賴的回歸測試。
目前支援 VB.NET，架構預留 Java 擴展。

**溝通語言：繁體中文。**

---

## Don't add claude as the contributor of this repo.

## 核心設計原則

> **能用確定性程式碼做到的，絕不寫成給模型的指示。**

小模型的可靠度來自結構性保證，不是來自 prompt。模型只負責填語意值，
不決定結構、順序、或格式。

具體地說，模型**不做**這些事：

- 不產生 SQL（FK 鏈、INSERT 順序、NOT NULL 填充由 planner 決定）
- 不產生 YAML（吐扁平 JSON，由 serializer 轉換）
- 不決定命名慣例、ID 區間、欄位順序（renderer 硬編碼）
- 不「去讀某個檔案」（orchestrator 主動注入片段——7–8B 常跳過讀取步驟）

## 架構

```
extractors/dotnet/   C# — Roslyn，吐語言無關的 spec.json
extractors/jvm/      (未來) JavaParser 或 Spoon，吐同樣格式
orchestrator/        Python — prompt 組裝/模型呼叫/驗證/重試/量測；templates/ 含 generate.md, patch.md（已重建）
pipeline/            Python — planner / renderer / validator
skill/               SKILL.md（路由/文件用，不注入模型 context）
domain/              domain.yaml — 跨專案時唯一要改的地方
```

工具鏈：Python 一律用 uv 跑（`uv run python -m unittest discover -s orchestrator/tests -t .`）；
模型呼叫走 opencode CLI（`opencode run -m provider/model`），不用 Ollama 直連。

**關鍵解耦**：spec.json 的格式是語言無關的。新增語言只需要新的 extractor，
下游一行都不用改。

## 已定案的決定（不要重新開題）

| 項目          | 決定                                                                 |
| ------------- | -------------------------------------------------------------------- |
| 測試隔離      | 保留 ID 區間（900000+），非 transaction rollback                     |
| Fixture 粒度  | 共用 base fixture + per-case 增量                                    |
| Domain config | 三層 fallback：exact > pattern > 型別預設；空 config 也要能跑        |
| Case 命名     | `Characterize_` 前綴——標示「現況」而非「正確」                       |
| patch 策略    | 只回傳單一欄位 `{"field","value"}`，Python 替換；不重生整份 artifact |
| Expected 來源 | golden master（跑舊碼抓現況），模型不參與                            |
| 本機執行 DB   | 一律真 DB2（Docker container）；ephemeral H2 已移除（復活看 dafd4e6） |

## 目前狀態與優先序

詳見 `docs/HANDOFF.md`（唯一事實來源）。摘要：

- **已完成**：seed planner 定案、renderer + 信任閘門三項（欄位排除／亂序／mutation）、
  extractor v1.1 + Mutator、orchestrator 接 planner ModelSlot、E2E 已用真模型
  （opencode/big-pickle）+ 真 DB2 跑通，bundle 契約零違規。
- **接下來**：extractor v2（block 呼叫鏈閉包，見 `docs/REQ_BLOCK_TRACING.md`）、
  公司側環境接真實 schema 實跑、block.md → block.yaml 轉換。

## 注意事項

- **不要 commit 真實 schema、表名、連線字串**。`domain/*.yaml` 與
  `schema/*.json` 已在 .gitignore；只有 `*.example.*` 進版控。
- 失敗要**先分類再修**：schema 錯 → constrained decoding；
  SQL 執行錯 → 修 planner（**retry 對這類永遠無效**）；
  語意不合理 → few-shot。
- 截止日 2026-08-31。8/26 後凍結架構，只跑 eval 與寫報告。
