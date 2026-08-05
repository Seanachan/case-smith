"""信任閘門(第二項):suite_manifest 整批亂序跑 3 次,結果不一致者踢除。

動機(docs/HANDOFF.md §4):CaseSmith 產的 case 有模型參與,可信賴度不能只
靠人審——要防「測試間有隱性順序依賴」這種 flaky 來源。跑法是把同一份
suite_manifest 的 tests[] 洗牌成 N 份、各自送框架跑一輪、把 N 份 result
JSON 的 per-case status 對齊比較:N 次都一樣 = stable,任何一次不一樣 =
kicked(順序敏感,不可信)。

本檔只管兩件確定性的事,不碰框架執行本身(需要使用者側 Java + DB2 環境):
    shuffle_manifests()  suite_manifest dict → N 份洗牌副本
    compare_runs()       N 份 result JSON dict → TrustGateReport

欄位形狀依 docs/ARTF_CONTRACT.md:
    Q6(suite_manifest)  tests: [<test_case.yaml 相對路徑>, ...]
    Q7(result JSON)     test_results[] 每筆 {test_case_id, status, profile,
                        ...},status ∈ passed|failed|blocked;多 provider 用
                        provider_summary[]/provider_results[],但那是
                        provider 層彙總,不影響這裡的 per-case 比較邏輯。
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

import yaml

# ---------------------------------------------------------------------------
# 亂序產生器
# ---------------------------------------------------------------------------


def shuffle_manifests(
    manifest: dict, runs: int = 3, seed: int = 20260805
) -> List[dict]:
    """suite_manifest dict → `runs` 份深拷貝,tests[] 順序各自洗牌。

    確定性:每份用獨立的 `random.Random(seed + i)` 洗牌,不碰全域 random
    狀態,同輸入(manifest, runs, seed)永遠同輸出。第 0 份保留原順序,當
    baseline 用;其餘欄位一律不動(只動 tests[] 這個 key)。
    """
    if runs < 1:
        raise ValueError(f"runs 必須 >= 1,收到 {runs!r}")
    out: List[dict] = []
    for i in range(runs):
        cloned = copy.deepcopy(manifest)
        if i > 0:
            tests = list(cloned.get("tests") or [])
            random.Random(seed + i).shuffle(tests)
            cloned["tests"] = tests
        out.append(cloned)
    return out


# ---------------------------------------------------------------------------
# 結果比較器
# ---------------------------------------------------------------------------


@dataclass
class TrustGateReport:
    stable: Dict[str, str] = field(default_factory=dict)
    kicked: Dict[str, List[str]] = field(default_factory=dict)

    def _stats(self) -> tuple:
        total = len(self.stable) + len(self.kicked)
        stable_n = len(self.stable)
        kicked_n = len(self.kicked)
        rate = (stable_n / total) if total else 0.0
        return total, stable_n, kicked_n, rate

    def summary(self) -> str:
        total, stable_n, kicked_n, rate = self._stats()
        return f"total={total} stable={stable_n} kicked={kicked_n} stable_rate={rate:.1%}"

    def to_json(self) -> str:
        total, stable_n, kicked_n, rate = self._stats()
        payload = {
            "total": total,
            "stable_count": stable_n,
            "kicked_count": kicked_n,
            "stable_rate": rate,
            "stable": self.stable,
            "kicked": self.kicked,
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _case_statuses(result: dict, run_index: int) -> Dict[str, str]:
    """單份 result JSON 的 test_results[] → {test_case_id: status}。

    id 缺漏或重複一律 raise,不靜默跳過(靜默跳過會讓 kicked 判定失真)。
    """
    statuses: Dict[str, str] = {}
    for entry in result.get("test_results") or []:
        case_id = entry.get("test_case_id")
        if not case_id:
            raise ValueError(f"run[{run_index}]: test_results 條目缺 test_case_id: {entry!r}")
        if case_id in statuses:
            raise ValueError(f"run[{run_index}]: test_case_id 重複出現: {case_id!r}")
        status = entry.get("status")
        if not status:
            raise ValueError(f"run[{run_index}]: test_case_id={case_id!r} 缺 status")
        statuses[case_id] = status
    return statuses


def compare_runs(results: List[dict]) -> TrustGateReport:
    """N 份 parse 好的 ARTF result JSON → TrustGateReport。

    以 test_case_id 對齊;任何一份的 case 集合與 run[0] 不同(缺一個或多
    一個都算)就 raise ValueError——這代表跑法本身不對等(例如某次沒選到
    全部 test),不是「這個 case flaky」,不能靜默吞掉當作 kicked。
    """
    if not results:
        raise ValueError("compare_runs: results 不可為空")

    per_run = [_case_statuses(r, i) for i, r in enumerate(results)]
    baseline_ids = frozenset(per_run[0])
    for i, statuses in enumerate(per_run):
        ids = frozenset(statuses)
        if ids != baseline_ids:
            missing = sorted(baseline_ids - ids)
            extra = sorted(ids - baseline_ids)
            raise ValueError(
                f"run[{i}] 的 case 集合與 run[0] 不一致(缺 {missing}, 多 {extra})"
            )

    stable: Dict[str, str] = {}
    kicked: Dict[str, List[str]] = {}
    for case_id in sorted(baseline_ids):
        run_statuses = [statuses[case_id] for statuses in per_run]
        if len(set(run_statuses)) == 1:
            stable[case_id] = run_statuses[0]
        else:
            kicked[case_id] = run_statuses
    return TrustGateReport(stable=stable, kicked=kicked)


# ---------------------------------------------------------------------------
# python -m pipeline.trust_gate:兩個子指令,不經 cli.py
# ---------------------------------------------------------------------------


def _cli(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m pipeline.trust_gate",
        description="信任閘門 harness:亂序產生 suite_manifest 副本 / 比較 N 份 result JSON。",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    p_shuffle = sub.add_parser("shuffle", help="suite_manifest.yaml → N 份亂序副本(落地 YAML)")
    p_shuffle.add_argument("--manifest", required=True, help="suite_manifest.yaml 路徑")
    p_shuffle.add_argument("--runs", type=int, default=3)
    p_shuffle.add_argument("--seed", type=int, default=20260805)
    p_shuffle.add_argument("--out-dir", required=True, help="輸出目錄,寫 run_0.yaml..run_{n-1}.yaml")

    p_compare = sub.add_parser("compare", help="N 份 result JSON → TrustGateReport")
    p_compare.add_argument("results", nargs="+", help="result JSON 檔路徑(至少 2 份)")
    p_compare.add_argument("--json", action="store_true", help="印完整 to_json() 而非只印 summary()")

    args = ap.parse_args(argv)

    if args.command == "shuffle":
        manifest = yaml.safe_load(Path(args.manifest).read_text(encoding="utf-8"))
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        for i, doc in enumerate(shuffle_manifests(manifest, runs=args.runs, seed=args.seed)):
            path = out_dir / f"run_{i}.yaml"
            path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
            print(f"[trust_gate] {path} ← {len(doc.get('tests') or [])} tests")
        return 0

    if args.command == "compare":
        if len(args.results) < 2:
            print("[trust_gate] compare 至少需要 2 份 result JSON 才有意義", file=sys.stderr)
            return 1
        results = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.results]
        report = compare_runs(results)
        if args.json:
            print(report.to_json())
        else:
            print(report.summary())
            for case_id, statuses in sorted(report.kicked.items()):
                print(f"  kicked: {case_id} -> {statuses}")
        return 0 if not report.kicked else 1

    return 1


if __name__ == "__main__":
    sys.exit(_cli())
