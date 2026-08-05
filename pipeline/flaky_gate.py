"""信任閘門②:同一批 case 亂序跑 N 次(預設 3),結果不一致者踢除。

輸入:N 份 ARTF result.json(形狀見 result.v0.2 契約;讀 test_results[]
的 test_case_id / status,status ∈ passed|failed|blocked)。
實際「亂序跑 N 次」由 ARTF runner 執行(java -jar ... run,suite 內順序
由 renderer 洗牌——待接);這裡是跑完之後的**判定器**,純函式可離線測。

分類:
- stable:N 次 status 完全一致且非 blocked。一致的 failed 也是 stable——
  那是真紅(現況與 golden master 不符),不是 flaky,要人看,不踢。
- flaky:N 次 status 不一致(且無 blocked)→ 踢除,不進交付集。
- undetermined:任一次 blocked(前置失敗,非受測行為)→ 不判定,回報人工。
- missing:某些 run 缺席(次數 != N)→ 同 flaky 處理,踢除並回報。

用法(CLI):
    uv run python -m pipeline.flaky_gate run1/result.json run2/result.json run3/result.json
exit 0 = 無 flaky/undetermined/missing;非 0 = 有,清單印在 stdout。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

BLOCKED = "blocked"


@dataclass(frozen=True)
class GateReport:
    stable: Dict[str, str] = field(default_factory=dict)        # case -> 一致的 status
    flaky: Dict[str, List[str]] = field(default_factory=dict)   # case -> 各次 status
    undetermined: Dict[str, List[str]] = field(default_factory=dict)
    missing: Dict[str, int] = field(default_factory=dict)       # case -> 出現次數

    @property
    def kept(self) -> Dict[str, str]:
        """通過閘門的 case(含一致 failed——真紅要留給人看)。"""
        return dict(self.stable)

    @property
    def clean(self) -> bool:
        return not (self.flaky or self.undetermined or self.missing)


def load_result(path: Path) -> Dict[str, str]:
    """result.json → {test_case_id: status}。讀 test_results[](多 case 安全),
    不讀頂層 status(單 case 捷徑,多 provider 時不可靠——result.v0.2 契約)。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: Dict[str, str] = {}
    for entry in data.get("test_results", []):
        out[entry["test_case_id"]] = entry["status"]
    if not out:
        raise ValueError(f"{path}: test_results 為空或缺失,不是有效的 result.json")
    return out


def evaluate(runs: List[Dict[str, str]]) -> GateReport:
    if len(runs) < 2:
        raise ValueError(f"至少要 2 份 run 才能判定一致性(收到 {len(runs)})")
    n = len(runs)
    all_cases = sorted({c for run in runs for c in run})
    report = GateReport()
    for case in all_cases:
        statuses = [run[case] for run in runs if case in run]
        if len(statuses) != n:
            report.missing[case] = len(statuses)
        elif BLOCKED in statuses:
            report.undetermined[case] = statuses
        elif len(set(statuses)) == 1:
            report.stable[case] = statuses[0]
        else:
            report.flaky[case] = statuses
    return report


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print(__doc__)
        return 2
    report = evaluate([load_result(Path(p)) for p in argv])
    for case, status in report.stable.items():
        print(f"STABLE       {case}: {status}")
    for case, statuses in report.flaky.items():
        print(f"FLAKY        {case}: {' -> '.join(statuses)}(踢除)")
    for case, statuses in report.undetermined.items():
        print(f"UNDETERMINED {case}: {' -> '.join(statuses)}(有 blocked,人工判定)")
    for case, count in report.missing.items():
        print(f"MISSING      {case}: 只出現 {count}/{len(argv)} 次(踢除)")
    print(f"[flaky-gate] kept={len(report.kept)} "
          f"flaky={len(report.flaky)} undetermined={len(report.undetermined)} "
          f"missing={len(report.missing)}")
    return 0 if report.clean else 1


if __name__ == "__main__":
    sys.exit(main())
