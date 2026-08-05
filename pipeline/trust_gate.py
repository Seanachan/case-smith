"""信任閘門②的洗牌側:suite_manifest 整批亂序成 N 份副本。

動機(docs/HANDOFF.md §6.4):防「測試間隱性順序依賴」。同一份
suite_manifest 的 tests[] 洗牌成 N 份、各自送框架跑一輪;跑完的 N 份
result JSON 交給 **pipeline/flaky_gate.py 判定**(stable / flaky 踢除 /
blocked 人工 / missing 踢除)——判定器只有那一個,本檔不重複實作。

本檔只管洗牌這件確定性的事,不碰框架執行本身(需要使用者側 Java + DB2):
    shuffle_manifests()  suite_manifest dict → N 份洗牌副本

欄位形狀依 docs/ARTF_CONTRACT.md Q6:tests: [<test_case.yaml 相對路徑>, ...]
"""

from __future__ import annotations

import argparse
import copy
import random
import sys
from pathlib import Path
from typing import List

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
# python -m pipeline.trust_gate:只有 shuffle;判定用 python -m pipeline.flaky_gate
# ---------------------------------------------------------------------------


def _cli(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m pipeline.trust_gate",
        description="亂序產生 suite_manifest 副本;跑完的 result 判定交給 pipeline.flaky_gate。",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    p_shuffle = sub.add_parser("shuffle", help="suite_manifest.yaml → N 份亂序副本(落地 YAML)")
    p_shuffle.add_argument("--manifest", required=True, help="suite_manifest.yaml 路徑")
    p_shuffle.add_argument("--runs", type=int, default=3)
    p_shuffle.add_argument("--seed", type=int, default=20260805)
    p_shuffle.add_argument("--out-dir", required=True, help="輸出目錄,寫 run_0.yaml..run_{n-1}.yaml")

    args = ap.parse_args(argv)

    manifest = yaml.safe_load(Path(args.manifest).read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, doc in enumerate(shuffle_manifests(manifest, runs=args.runs, seed=args.seed)):
        path = out_dir / f"run_{i}.yaml"
        path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
        print(f"[trust_gate] {path} ← {len(doc.get('tests') or [])} tests")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
