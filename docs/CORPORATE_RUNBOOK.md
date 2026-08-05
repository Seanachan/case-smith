# 公司環境 Runbook

到公司(真 VB 專案、真 schema、真 DB2)之後照這份跑。
原則:**程式碼、schema、表名、連線字串不出公司;帶出來的只有去識別的量測數據與教訓。**

## 出發前(在家做完)

- [ ] case-smith repo 拉到最新;ARTF repo + build 好的 jar 一起帶(公司內網可能不能 `./mvnw` 抓依賴)
- [ ] jcc driver jar(`drivers/db2/jcc.jar`)帶著——內網抓不了 Maven Central
- [ ] **確認公司內的模型管道**(最大未知數):opencode 免費模型要外網。
  內網不通的話選項:(a) 內部 ollama/vLLM endpoint → `OpencodeClient` 換
  provider 字串或 opencode 配 local provider;(b) 都沒有 → 寫新 `ModelClient`
  (protocol 只有一個 `generate(prompt) -> str` 方法,半小時的事)
- [ ] uv / dotnet SDK 9 / Java 17 安裝檔(內網可能不能線上裝)

## Day 1:環境 + 材料檢查

```bash
uv --version && dotnet --version && java -version   # 三件工具
opencode models                                      # 模型管道通不通(見上)
```

1. **Schema 進場**:DB2 DDL export → 你的 `ddl2json.mjs` → schema.json
   (形狀對齊 `schema/schema.example.json` 契約)。
   - **先掃組合 FK**:`grep -c "FOREIGN KEY (.*,)" <ddl>`——
     **已知限制:多欄 FK planner 不支援**,有就先回報再說,不要硬跑。
   - 真 schema 跑一次 planner 測試:`uv run pytest pipeline/test_seed_planner.py -q`
2. **Extractor 進場**:
   ```bash
   cd extractors/dotnet
   dotnet run --project CaseSmith.Extractor -- --input <真VB專案目錄> --output /安全路徑/spec.json
   ```
   抽查 3-5 個方法:SQL 常數抽得全嗎?`dynamic_sql: true` 比率多高?
   (比率高 → 常數字串假設不成立,早知道早調整)
3. **Domain config**:照 `domain/domain.example.yaml` 填真值
   (真表名版**只放公司機器**,已在 .gitignore)。

## Day 1-2:第一條真 case

4. **ID 區間確認**:900000–999999 在公司測試庫沒人用(問 DBA 或 SELECT 掃一次)。
5. 產第一個 case + 框架驗:
   ```bash
   uv run python -m pipeline.cli --spec /安全路徑/spec.json --schema /安全路徑/schema.json \
       --domain /安全路徑/domain.yaml --method <挑條件欄位最少的方法> --out /安全路徑/run1
   java -jar <artf>/target/spec-driven-auto-regression-0.2.7.jar validate \
       --suite /安全路徑/run1/bundle/suite_manifest.yaml
   ```
6. **真跑**(公司 DB2 測試 schema):
   ```bash
   export JDBC_CONNECTION='jdbc:db2://<host>:<port>/<db>:user=<u>;password=<p>;'
   java -jar ... run --suite .../suite_manifest.yaml --profile local_fake \
       --driver-path drivers/db2/jcc.jar
   ```
7. **Golden master**:recording run 抓現況 → expected(見 `docs/USAGE.md` ⑦)。

## Day 2+:批量與量測

8. Block markdown → 錨點(`docs/REQ_BLOCK_TRACING.md` 流程)→ block spec → 批量產 case。
9. 亂序 3 次 + flaky gate:`scripts/shuffled_runs.py` → `pipeline/flaky_gate.py`。
10. 量測收集:`runs.jsonl` + result.json 彙整。

## 帶出公司前(必做)

- [ ] `runs.jsonl` 逐行檢查:**slot 名含真表名欄名 → 去識別**(sed 換成 T1.C1 之類)再帶出
- [ ] 帶出:去識別量測數據、eval 曲線、失敗分類統計、問題/教訓清單
- [ ] 不帶出:spec.json、schema.json、domain.yaml(真值版)、任何 bundle 產物
- [ ] `git status` 確認沒把公司檔案 stage 進去(.gitignore 已擋 domain/schema,但 out/ 之外的自建路徑要自己看)

## 預期會出事的點(先有心理準備)

| 症狀 | 對策 |
|---|---|
| 組合 FK 存在 | 停,回報;planner 要補(已知限制) |
| dynamic_sql 比率高 | 常數 SQL 假設弱化;記數字,選常數比率高的模組先做 |
| 模型管道不通 | 換 ModelClient(見出發前清單) |
| ID 區間有人用 | 換區間(`SeedPlanner.ID_START/ID_END` + `render_artifacts.ID_START/ID_END`) |
| DB2 方言差異(真環境 vs example) | 失敗分類:SQL_EXEC → 修 planner/emit_sql,**不要 retry** |
