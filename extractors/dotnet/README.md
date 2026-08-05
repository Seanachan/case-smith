# dotnet extractor

VB.NET spec 抽取器 v1(syntax-level)。直接 parse `.vb` 檔(`VisualBasicSyntaxTree.ParseText`),
不用 MSBuildWorkspace/編譯——legacy .NET Framework 的 `.sln` 在 mac 上大概率載不動,而
簽章、分支數、常數 SQL、endpoint 常數全部語法層可得。輸出形狀見
[`../../docs/CONTRACTS.md`](../../docs/CONTRACTS.md#spec-cardspecjson契約-v1)、
範例見 [`../spec_card.example.json`](../spec_card.example.json)(對 `CaseSmith.Extractor.Tests/Fixtures/`
實跑的輸出)。

## 本機跑法(dotnet 9.0.101,已驗證可行,不需要 Docker)

```bash
# build
dotnet build

# test(CaseSmith.Extractor.Tests,13 個 xunit 案例)
dotnet test

# 實跑:掃一個目錄的 *.vb,吐 spec.json
dotnet run --project CaseSmith.Extractor -- --input <目錄> --output <檔案>

# 例:對 fixtures 實跑,重新產生 ../spec_card.example.json
dotnet run --project CaseSmith.Extractor -- --input CaseSmith.Extractor.Tests/Fixtures --output ../spec_card.example.json
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
```

## 已知限制(v1 syntax-level)

- 不做跨方法資料流(semantic 需求留 v2)。
- SQL 變數解析只認「同方法內單次指派」(`Dim x As String = "..."`,之後未被重新指派);
  多次指派或跨方法傳遞一律視為非常數,標 `dynamic_sql: true`。
- WHERE/ON 條件欄位抽取用 regex,不解析別名(alias)——多表語境的裸欄名一律進
  `unqualified_condition_columns`,不猜表名。
