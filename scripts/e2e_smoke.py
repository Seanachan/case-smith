"""Live smoke:同一條 E2E 路,但模型走真的 opencode CLI。

用法(repo root):
    uv run python scripts/e2e_smoke.py [--model opencode/big-pickle] [--out out/e2e_smoke]

網路 + opencode 登入依賴,故不進測試套件;驗證的是 transport 接線,
不是模型品質(7–8B 合規性見 HANDOFF §4 E2E 路線決定)。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402

from orchestrator.client import OpencodeClient  # noqa: E402
from orchestrator.core import GenerationFailed, Orchestrator  # noqa: E402
from orchestrator.metrics import MetricsLog  # noqa: E402
from pipeline.contract_check import check_suite_manifest, check_test_case  # noqa: E402
from pipeline.render_artifacts import CaseBundleSpec, render_bundle, write_bundle  # noqa: E402
from pipeline.seed_planner import DomainConfig, Schema, SeedPlanner  # noqa: E402

CASE_ID = "Characterize_UpdateOrderStatus_Default"
CONTEXT = (
    "Public Sub UpdateOrderStatus(orderId As Decimal, statusCd As String)\n"
    "    ' UPDATE T_ORDER SET STATUS_CD = @statusCd WHERE ORDER_ID = @orderId\n"
    "End Sub"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="opencode/big-pickle")
    ap.add_argument("--out", default="out/e2e_smoke")
    ap.add_argument("--timeout", type=float, default=180.0)
    args = ap.parse_args()

    out_dir = REPO_ROOT / args.out
    schema = Schema.from_json(
        json.loads((REPO_ROOT / "schema" / "schema.example.json").read_text("utf-8"))
    )
    planner = SeedPlanner(schema, DomainConfig(), ask_model=["T_ORDER.STATUS_CD"])
    base = planner.plan_base(["T_ORDER"])
    case_row = planner.plan_case("T_ORDER", CASE_ID)

    out_dir.mkdir(parents=True, exist_ok=True)
    metrics = MetricsLog(out_dir / "runs.jsonl")
    orch = Orchestrator(
        OpencodeClient(model=args.model, timeout=args.timeout), metrics=metrics
    )

    print(f"[smoke] model={args.model} slots={[s.name for s in case_row.slots]}")
    try:
        result = orch.run_generate(CASE_ID, CONTEXT, case_row.slots)
    except GenerationFailed as exc:
        print(f"[smoke] FAILED after retries: {exc}")
        for i, failure in enumerate(exc.attempts, 1):
            print(f"  attempt {i}: {failure.cls.value}: {failure.detail[:200]}")
        return 1

    print(f"[smoke] values={result.values} attempts={result.attempts}")

    spec = CaseBundleSpec(
        case_id=CASE_ID,
        title="Characterize UpdateOrderStatus current behaviour",
        suite_id="CASESMITH-SMOKE",
    )
    files = render_bundle(spec, schema, base, case_row, result.values)
    write_bundle(files, out_dir / "bundle")

    tc = yaml.safe_load(files[f"test_cases/{CASE_ID}.yaml"])
    sm = yaml.safe_load(files["suite_manifest.yaml"])
    violations = check_test_case(tc) + check_suite_manifest(sm)
    print(f"[smoke] contract violations: {violations or 'none'}")
    print(f"[smoke] bundle: {out_dir / 'bundle'}({len(files)} files)")
    print(f"[smoke] metrics: {json.dumps(metrics.summary())}")
    return 0 if not violations else 1


if __name__ == "__main__":
    sys.exit(main())
