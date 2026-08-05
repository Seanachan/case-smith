"""信任閘門②執行端:亂序跑 N 次 + flaky 判定,一條指令。

    export JDBC_CONNECTION='jdbc:db2://...'
    uv run python scripts/shuffled_runs.py \
        --bundle out/prefix_test/bundle \
        --artf   ~/Auto_Regression_Test_Framework \
        --runs 3

流程:pipeline.trust_gate.shuffle_manifests 產 N 份亂序 suite_manifest
(寫進 bundle 目錄,artifact 相對路徑才解析得到)→ 逐份呼叫 ARTF runner
→ 收集各次 result.json → pipeline.flaky_gate 判定。exit code 同 flaky_gate
(0 = 無 flaky/undetermined/missing)。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402

from pipeline.flaky_gate import evaluate, load_result  # noqa: E402
from pipeline.trust_gate import shuffle_manifests  # noqa: E402

RESULT_RE = re.compile(r"^result_json:\s*(\S+)", re.MULTILINE)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True, help="CaseSmith bundle 目錄(含 suite_manifest.yaml)")
    ap.add_argument("--artf", required=True, help="ARTF repo 根目錄(含 target/*.jar 與 drivers/)")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--seed", type=int, default=20260805)
    ap.add_argument("--profile", default="local_fake")
    ap.add_argument("--driver-path", default="drivers/db2/jcc.jar", help="相對 --artf 的 driver 路徑")
    args = ap.parse_args()

    if "JDBC_CONNECTION" not in os.environ:
        print("JDBC_CONNECTION 未設,先 export(格式見 docs/USAGE.md §⑥)")
        return 2

    artf = Path(args.artf).expanduser()
    jars = sorted(artf.glob("target/spec-driven-auto-regression-*.jar"))
    if not jars:
        print(f"{artf}/target 下找不到 runner jar,先 ./mvnw -DskipTests package")
        return 2
    jar = jars[-1]

    bundle = Path(args.bundle).resolve()
    manifest = yaml.safe_load((bundle / "suite_manifest.yaml").read_text(encoding="utf-8"))

    results = []
    for i, doc in enumerate(shuffle_manifests(manifest, runs=args.runs, seed=args.seed)):
        run_manifest = bundle / f"suite_manifest.run_{i}.yaml"
        run_manifest.write_text(
            yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        print(f"[shuffled-runs] run {i}: tests={doc.get('tests')}")
        proc = subprocess.run(
            ["java", "-jar", str(jar), "run", "--suite", str(run_manifest),
             "--profile", args.profile, "--driver-path", args.driver_path],
            cwd=artf, capture_output=True, text=True, timeout=600,
        )
        match = RESULT_RE.search(proc.stdout)
        if not match:
            print(f"[shuffled-runs] run {i} 沒吐 result_json,runner 輸出尾段:")
            print("\n".join(proc.stdout.splitlines()[-8:]))
            return 2
        result_path = artf / match.group(1)
        results.append(load_result(result_path))
        print(f"[shuffled-runs] run {i} → {result_path}")

    report = evaluate(results)
    for case, status in report.stable.items():
        print(f"STABLE       {case}: {status}")
    for case, seen in report.flaky.items():
        print(f"FLAKY        {case}: {' -> '.join(seen)}(踢除)")
    for case, seen in report.undetermined.items():
        print(f"UNDETERMINED {case}: {' -> '.join(seen)}")
    for case, count in report.missing.items():
        print(f"MISSING      {case}: {count}/{args.runs}")
    print(f"[shuffled-runs] kept={len(report.kept)} flaky={len(report.flaky)} "
          f"undetermined={len(report.undetermined)} missing={len(report.missing)}")
    return 0 if report.clean else 1


if __name__ == "__main__":
    sys.exit(main())
