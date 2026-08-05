"""Eval 報告:量測數據 → v1→vN markdown 報告(HANDOFF §6.5 的報告端)。

輸入兩類,都可多份:
- runs.jsonl:orchestrator MetricsLog 產物(模型層——first-pass rate、
  錯誤分類,按 template_version 分組 → 改進曲線)
- result.json:ARTF 執行層(test_results[].status);≥2 份自動附 flaky gate

用法:
    uv run python -m pipeline.eval_report \
        --runs out/*/runs.jsonl \
        --results run1/result.json run2/result.json run3/result.json \
        --out eval_report.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pipeline.flaky_gate import GateReport, evaluate, load_result

_CLASSES = ("schema", "semantic", "sql_exec")


def aggregate_runs(paths: List[Path]) -> Dict[str, dict]:
    """runs.jsonl(可多份)→ {template_version: 統計}。
    first-pass 判定同 MetricsLog.summary:case 第一筆 attempt 即 pass。"""
    by_ver: Dict[str, dict] = {}
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            v = by_ver.setdefault(row["template_version"], {
                "first": {}, "by_class": {}, "attempts": 0,
            })
            v["attempts"] += 1
            case = row["case_id"]
            if row["attempt"] == 1 and case not in v["first"]:
                v["first"][case] = row["outcome"]
            if row["outcome"] != "pass":
                v["by_class"][row["outcome"]] = v["by_class"].get(row["outcome"], 0) + 1
    return by_ver


def _framework_counts(results: Dict[str, str]) -> Dict[str, int]:
    counts = {"passed": 0, "failed": 0, "blocked": 0}
    for status in results.values():
        counts[status] = counts.get(status, 0) + 1
    return counts


def render_report(by_ver: Dict[str, dict],
                  results: List[Tuple[str, Dict[str, str]]],
                  gate: Optional[GateReport]) -> str:
    lines = ["# CaseSmith eval report", ""]

    lines.append("## 模型層(orchestrator,按 template 版本)")
    lines.append("")
    lines.append("| template | cases | first-pass rate | " + " | ".join(_CLASSES) + " |")
    lines.append("|---|---|---|" + "---|" * len(_CLASSES))
    for ver in sorted(by_ver):
        v = by_ver[ver]
        total = len(v["first"])
        passed = sum(1 for o in v["first"].values() if o == "pass")
        rate = f"{passed / total:.0%}" if total else "-"
        cls = " | ".join(str(v["by_class"].get(c, 0)) for c in _CLASSES)
        lines.append(f"| {ver} | {total} | {rate} | {cls} |")
    if not by_ver:
        lines.append("| (無資料) | - | - | " + " | ".join("-" for _ in _CLASSES) + " |")
    lines.append("")

    if results:
        lines.append("## 執行層(ARTF result.json)")
        lines.append("")
        lines.append("| result | passed | failed | blocked |")
        lines.append("|---|---|---|---|")
        for name, res in results:
            c = _framework_counts(res)
            lines.append(f"| {name} | {c['passed']} | {c['failed']} | {c['blocked']} |")
        lines.append("")

    if gate is not None:
        lines.append("## Flaky gate(多次執行一致性)")
        lines.append("")
        lines.append(f"- stable(交付集): {len(gate.stable)}")
        lines.append(f"- flaky(踢除): {len(gate.flaky)}")
        lines.append(f"- undetermined(有 blocked,人工): {len(gate.undetermined)}")
        lines.append(f"- missing(缺席,踢除): {len(gate.missing)}")
        for case, statuses in gate.flaky.items():
            lines.append(f"  - FLAKY {case}: {' -> '.join(statuses)}")
        lines.append("")

    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="eval_report", description=__doc__)
    ap.add_argument("--runs", nargs="*", default=[], help="runs.jsonl 路徑(可多份)")
    ap.add_argument("--results", nargs="*", default=[], help="ARTF result.json 路徑(可多份)")
    ap.add_argument("--out", default="eval_report.md", help="輸出 markdown 路徑")
    args = ap.parse_args(argv)

    if not args.runs and not args.results:
        ap.error("至少給 --runs 或 --results 其中一種輸入")

    by_ver = aggregate_runs([Path(p) for p in args.runs])
    results = [(Path(p).name if len(Path(p).parts) < 2 else str(Path(p).parent.name) + "/" + Path(p).name,
                load_result(Path(p))) for p in args.results]
    gate = evaluate([r for _, r in results]) if len(results) >= 2 else None

    report = render_report(by_ver, results, gate)
    Path(args.out).write_text(report, encoding="utf-8")
    print(f"[eval-report] → {args.out}")
    if gate is not None and not gate.clean:
        print("[eval-report] !! flaky/undetermined/missing 存在,交付集要剔除,詳見報告")
    return 0


if __name__ == "__main__":
    sys.exit(main())
