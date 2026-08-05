# dotnet extractor

兩個獨立 CLI 專案，共用同一個 solution（`CaseSmith.Extractor.sln`）：

- **`CaseSmith.Extractor`**——VB.NET spec 抽取器 v1(syntax-level)。直接 parse `.vb` 檔
  (`VisualBasicSyntaxTree.ParseText`)，不用 MSBuildWorkspace/編譯——legacy .NET Framework
  的 `.sln` 在 mac 上大概率載不動，而簽章、分支數、常數 SQL、endpoint 常數全部語法層
  可得。輸出形狀見 [`../../docs/CONTRACTS.md`](../../docs/CONTRACTS.md#spec-cardspecjson契約-v1)、
  範例見 [`../spec_card.example.json`](../spec_card.example.json)(對 `CaseSmith.Extractor.Tests/Fixtures/`
  實跑的輸出)。
- **`CaseSmith.Mutator`**——mutation testing 產生器，測試品質的篩選閘（見下方
  「CaseSmith.Mutator」節）。

## 本機跑法(dotnet 9.0.101,已驗證可行,不需要 Docker)

```bash
# build(整個 solution:Extractor + Mutator + 兩份測試專案)
dotnet build

# test(CaseSmith.Extractor.Tests 14 + CaseSmith.Mutator.Tests 8 = 22 個 xunit 案例)
dotnet test

# 實跑 Extractor:掃一個目錄的 *.vb,吐 spec.json
dotnet run --project CaseSmith.Extractor -- --input <目錄> --output <檔案>

# 例:對 fixtures 實跑,重新產生 ../spec_card.example.json
dotnet run --project CaseSmith.Extractor -- --input CaseSmith.Extractor.Tests/Fixtures --output ../spec_card.example.json

# 實跑 Mutator:掃一個目錄的 *.vb,吐 mutant 樹 + manifest.json
dotnet run --project CaseSmith.Mutator -- --input <目錄> --output <輸出目錄>
```

## Docker 備援(本機沒裝 dotnet SDK 時)

```bash
docker run --rm -v "$PWD":/src -w /src mcr.microsoft.com/dotnet/sdk:9.0 dotnet test
```

## 專案佈局

```
CaseSmith.Extractor.sln
CaseSmith.Extractor/          console,套件只有 Microsoft.CodeAnalysis.VisualBasic(+隱含依賴)
  Program.cs                  CLI:--input <dir> 遞迴掃 *.vb、--output <file>
  Models.cs                   spec card POCO(對應 CONTRACTS.md 的欄位/巢狀)
  MethodExtractor.cs          走 Sub/Function、簽章、branch_count、命名空間/型別解析
  SqlAnalyzer.cs               SQL 常數收集(單次指派區域變數追蹤、& 串接攤平)+ regex 抽 table/欄位
  EndpointAnalyzer.cs          HTTP endpoint 偵測(WebRequest/Uri/HttpClient/WebClient)
CaseSmith.Extractor.Tests/    xunit
  Fixtures/                   三個假 VB 檔(表名對齊 schema/schema.example.json)
CaseSmith.Mutator/            console,同樣只依賴 Microsoft.CodeAnalysis.VisualBasic
  Program.cs                  CLI:--input <dir>、--output <dir>(寫 mutants/ 樹 + manifest.json)
  Models.cs                   manifest POCO(MutantManifest/MutantRecord/SkippedMutantRecord)
  MutationOperators.cs        三類運算子的語法樹改寫規則
  MutantGenerator.cs          走訪語法樹產生候選、re-parse 驗證、寫 mutant 樹、manifest 排序
CaseSmith.Mutator.Tests/      xunit
```

## 已知限制(v1 syntax-level, Extractor)

- 不做跨方法資料流(semantic 需求留 v2,見 `docs/REQ_BLOCK_TRACING.md`)。
- SQL 變數解析只認「同方法內單次指派」(`Dim x As String = "..."`,之後未被重新指派);
  多次指派或跨方法傳遞一律視為非常數,標 `dynamic_sql: true`。
- WHERE/ON 條件欄位抽取用 regex,不解析別名(alias)——多表語境的裸欄名一律進
  `unqualified_condition_columns`,不猜表名。

## CaseSmith.Mutator

Mutation testing 產生器：對 `.vb` 原始碼做**單點語法樹層級**改寫，產出一批 mutant 檔＋
`manifest.json`。用途是**測試品質的篩選閘**——好的回歸測試套件應該能殺死這些行為變異；
「跑 mutant 殺不殺」（rebuild + run suite）是使用者側 framework 的事，這個工具只負責
產生 mutant，不執行測試。

### CLI 用法

```bash
dotnet run --project CaseSmith.Mutator -- --input <dir> --output <dir>
```

- `--input`：VB 原始碼目錄，遞迴掃 `*.vb`。
- `--output`：輸出目錄，寫入 `<output>/mutants/<mutant-id>/...`（每個 mutant 一份完整
  檔案樹的相對路徑拷貝，只有目標檔內容被改寫）＋ `<output>/manifest.json`。

### 三類運算子（純語法樹操作，字串 literal 不碰——SQL 常數安全）

| 運算子 | 對象 | 改寫方式 |
|---|---|---|
| `compare_invert` | 比較運算式(`=`/`<>`/`<`/`<=`/`>`/`>=`) | 反轉為對應的相反比較(如 `=`→`<>`、`<`→`>=`) |
| `arithmetic_swap` | 算術運算式(`+`/`-`/`*`/`\`整數除) | 互換為對應運算(如 `+`↔`-`、`*`↔`\`) |
| `boolean_flip` | 布林字面值(`True`/`False`) | 互換 |

每個候選都來自真實的 `BinaryExpressionSyntax`/`LiteralExpressionSyntax` 節點（Roslyn
語法樹層級操作，不會把字串 literal 內容當成可改寫的 token）；產生後**必須 re-parse
成功**才收錄進 manifest，re-parse 失敗的候選記在 `skipped[]`（附 `reason`，不是靜默丟棄）。

### manifest.json 形狀

> `docs/CONTRACTS.md` 目前**未收錄** Mutator 的 manifest 契約（只有 spec card／ARTF
> 輸出契約）；以下形狀取自 `CaseSmith.Mutator/Models.cs` 原始碼，非引用既有文件——
> 若要釘成正式契約，建議之後補進 CONTRACTS.md。

```json
{
  "source": {"language": "vb.net", "tool": "casesmith-mutator", "version": 1},
  "mutants": [
    {"id": "...", "file": "相對路徑.vb", "line": 42, "operator": "compare_invert",
     "original": "...", "mutated": "..."}
  ],
  "skipped": [
    {"id": "...", "file": "相對路徑.vb", "line": 42, "operator": "arithmetic_swap",
     "original": "...", "mutated": "...", "reason": "re-parse failed"}
  ]
}
```

`mutants[]`／`skipped[]` 皆依確定性排序輸出（manifest 內容穩定，可 diff）。
