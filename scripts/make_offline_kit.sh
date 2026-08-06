#!/usr/bin/env bash
# 離線安裝包:公司機器無外網(GitHub/PyPI/NuGet 全不通)時,隨身碟帶進去的全部東西。
# 在家(有網路的 Mac)跑本腳本,產物在 out/offline_kit/。
#
# 內容:
#   casesmith.bundle           git bundle(含完整歷史,git clone 可直接吃)
#   casesmith-src.zip          純原始碼(公司沒 git 時的備援)
#   wheels/                    Python 依賴 wheel(win_amd64 + manylinux,py3.11-3.13)
#   extractor-win-x64/         Extractor + Mutator self-contained 發布(免 .NET SDK/NuGet)
#   artf/                      ARTF fat jar + DB2 jcc driver(免 Maven)
#   KIT_README.md              公司側離線安裝步驟
set -euo pipefail
cd "$(dirname "$0")/.."

KIT=out/offline_kit
rm -rf "$KIT"
mkdir -p "$KIT/wheels" "$KIT/artf"

echo "== 1/5 repo 打包 =="
git bundle create "$KIT/casesmith.bundle" main
git archive -o "$KIT/casesmith-src.zip" main

echo "== 2/5 Python wheels(跨平台)=="
uv export --no-hashes --format requirements-txt -o "$KIT/requirements.txt"
for plat in win_amd64 manylinux2014_x86_64; do
  for py in 311 312 313; do
    python3 -m pip download -q -r "$KIT/requirements.txt" -d "$KIT/wheels" \
      --only-binary=:all: --platform "$plat" \
      --python-version "$py" --implementation cp || \
      echo "  (略過 $plat/cp$py:某些套件無該組合 wheel)"
  done
done

echo "== 3/5 Extractor/Mutator self-contained(win-x64)=="
(cd extractors/dotnet && \
  dotnet publish CaseSmith.Extractor -c Release -r win-x64 --self-contained \
    -o "../../$KIT/extractor-win-x64/extractor" -v q && \
  dotnet publish CaseSmith.Mutator -c Release -r win-x64 --self-contained \
    -o "../../$KIT/extractor-win-x64/mutator" -v q)

echo "== 4/5 ARTF jar + driver =="
ARTF_JAR=$(ls "$HOME"/Auto_Regression_Test_Framework/target/spec-driven-auto-regression-*.jar 2>/dev/null | head -1)
if [ -n "$ARTF_JAR" ]; then
  cp "$ARTF_JAR" "$KIT/artf/"
else
  echo "  !! 找不到 ARTF jar(先去 ARTF repo ./mvnw -DskipTests package)"
fi
cp "$HOME"/Auto_Regression_Test_Framework/drivers/db2/jcc.jar "$KIT/artf/" 2>/dev/null \
  || echo "  !! 找不到 jcc.jar"

echo "== 5/5 KIT_README =="
cat > "$KIT/KIT_README.md" <<'EOF'
# CaseSmith 離線安裝包 — 公司側步驟(全程免外網)

前提:公司機器有 Python 3.11+、Java 17+(跑 ARTF 才要)。uv 不需要。

## 1. 還原 repo

    git clone casesmith.bundle casesmith        # 有 git
    # 或解壓 casesmith-src.zip(無 git 備援)

## 2. Python 環境(離線)

    cd casesmith
    python -m venv .venv
    .venv\Scripts\activate                      # Windows(Linux: source .venv/bin/activate)
    pip install --no-index --find-links ..\wheels -r ..\requirements.txt

## 3. 驗環境(數字對上 = 環境 OK)

    python -m pytest pipeline/ -q               # 104 passed
    python -m unittest discover -s orchestrator/tests -t .   # 25 OK

    (文件裡的 `uv run python ...` 在公司一律讀作 venv 啟用後的 `python ...`)

## 4. Extractor(免 SDK,直接跑發布檔)

    ..\extractor-win-x64\extractor\CaseSmith.Extractor.exe --input <VB專案目錄> --output spec.json

## 5. ARTF

    java -jar ..\artf\spec-driven-auto-regression-0.2.7.jar validate --suite <bundle>\suite_manifest.yaml
    # run 時加 --driver-path ..\artf\jcc.jar;連線設定見 docs/CORPORATE_RUNBOOK.md

## 6. 模型管道

    本包不含模型 runtime(體積因素)。公司內選項見 docs/CORPORATE_RUNBOOK.md
    「出發前」節:內部 ollama/vLLM endpoint,或自寫 ModelClient。

之後照 docs/CORPORATE_SETUP.md(架環境)→ docs/CORPORATE_RUNBOOK.md(操作順序)。
EOF

echo "== 完成 =="
du -sh "$KIT"
ls "$KIT"
