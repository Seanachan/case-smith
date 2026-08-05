"""CaseSmith 總指揮 CLI:spec.json + schema.json → ARTF bundle,一條指令。

    uv run python -m pipeline.cli \
        --spec   extractors/spec_card.example.json \
        --schema schema/schema.example.json \
        --domain domain/domain.example.yaml \
        --method GetActiveCustomer \
        --model  opencode/big-pickle \
        --out    out/demo

    # 只列出 spec 裡有哪些方法可選:
    uv run python -m pipeline.cli --spec ... --schema ... --list

串接順序(全部確定性,模型只在 ④ 填值):
① 讀 spec card 挑方法 → ② condition_columns 過濾成 ask_model 白名單
(排除 PK/FK——ID 歸 planner 配,不問模型)→ ③ planner 出 SeedPlan+slots
→ ④ orchestrator 問模型 → ⑤ renderer 出 bundle → ⑥ 契約檢查。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from orchestrator.client import FakeClient, OpencodeClient
from orchestrator.core import GenerationFailed, Orchestrator
from orchestrator.metrics import MetricsLog
from pipeline.contract_check import check_suite_manifest, check_test_case
from pipeline.render_artifacts import (
    CaseBundleSpec,
    render_bundle,
    verify_ignore_for,
    write_bundle,
)
from pipeline.seed_planner import DomainConfig, Schema, SeedPlanner


def _pick_method(spec_card: dict, name: str) -> dict:
    matches = [
        m for m in spec_card["methods"]
        if m["signature"]["name"] == name or m["id"] == name or m["id"].endswith("." + name)
    ]
    if not matches:
        raise SystemExit(f"spec 裡找不到方法 {name!r}(用 --list 看可選清單)")
    if len(matches) > 1:
        ids = ", ".join(m["id"] for m in matches)
        raise SystemExit(f"方法名 {name!r} 有多個匹配,請用完整 id:{ids}")
    return matches[0]


def _ask_model_whitelist(method: dict, schema: Schema) -> list:
    """condition_columns → ask_model:排除 PK/FK(ID 歸 planner),排除 schema 查無的欄。"""
    whitelist = []
    for key in method.get("condition_columns", []):
        table_name, _, col_name = key.partition(".")
        table = schema.tables.get(table_name)
        if table is None or not any(c.name == col_name for c in table.columns):
            continue
        if col_name in table.primary_key:
            continue
        if any(col_name in fk.columns for fk in table.foreign_keys):
            continue
        whitelist.append(key)
    return whitelist


def _method_context(method: dict) -> str:
    """spec card → 注入模型的最小事實(模型不讀檔,一律用塞的)。"""
    sig = method["signature"]
    params = ", ".join(f"{p['name']} As {p['type']}" for p in sig["params"])
    tables = "; ".join(
        f"{t['name']} ({'/'.join(t['operations'])})" for t in method.get("tables", [])
    )
    lines = [
        f"Method: {sig['name']}({params})" + (f" As {sig['returns']}" if sig["returns"] else ""),
        f"Source: {method['file']}:{method['line']}",
        f"Tables touched: {tables or 'none'}",
    ]
    if method.get("condition_columns"):
        lines.append("Condition columns: " + ", ".join(method["condition_columns"]))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="casesmith", description=__doc__)
    ap.add_argument("--spec", required=True, help="extractor 產的 spec card JSON")
    ap.add_argument("--schema", required=True, help="schema JSON(契約形狀見 schema.example.json)")
    ap.add_argument("--domain", help="domain config YAML(選填,空 config 也能跑)")
    ap.add_argument("--method", help="方法名或完整 id")
    ap.add_argument("--model", default="opencode/big-pickle", help="opencode 的 provider/model")
    ap.add_argument("--out", default="out/casesmith", help="bundle 輸出目錄")
    ap.add_argument("--list", action="store_true", help="列出 spec 裡的方法後結束")
    ap.add_argument("--fake", help='測試用:跳過真模型,直接給 JSON 值,如 \'{"T_X.COL": "V"}\'')
    ap.add_argument("--ephemeral", action="store_true",
                    help="bundle 針對框架自管 H2(含 DDL bootstrap,免 Docker/JDBC_CONNECTION)")
    args = ap.parse_args(argv)

    spec_card = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    schema = Schema.from_json(json.loads(Path(args.schema).read_text(encoding="utf-8")))

    if args.list:
        for m in spec_card["methods"]:
            cols = ", ".join(m.get("condition_columns", [])) or "-"
            print(f"{m['signature']['name']:30s} {m['id']}  [{cols}]")
        return 0
    if not args.method:
        ap.error("--method 必填(或用 --list 看可選)")

    domain = DomainConfig.from_yaml(args.domain) if args.domain else DomainConfig()
    method = _pick_method(spec_card, args.method)
    tables = [t["name"] for t in method.get("tables", [])]
    if not tables:
        raise SystemExit(f"{args.method}: spec 裡沒有觸及任何表,無 seed 可產")
    ask_model = _ask_model_whitelist(method, schema)
    case_id = f"Characterize_{method['signature']['name']}_Default"
    print(f"[casesmith] method={method['id']}")
    print(f"[casesmith] tables={tables} ask_model={ask_model or '(無——全部欄位由 planner 填)'}")

    # ③ planner
    planner = SeedPlanner(schema, domain, ask_model=ask_model)
    base = planner.plan_base(tables)
    case_row = planner.plan_case(tables[0], case_id)

    # ④ orchestrator(有 slot 才問模型)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    values: dict = {}
    if case_row.slots:
        if args.fake is not None:
            client = FakeClient([args.fake])
        else:
            client = OpencodeClient(model=args.model)
        orch = Orchestrator(client, metrics=MetricsLog(out_dir / "runs.jsonl"))
        try:
            result = orch.run_generate(case_id, _method_context(method), case_row.slots)
        except GenerationFailed as exc:
            print(f"[casesmith] 生成失敗:{exc}")
            for i, failure in enumerate(exc.attempts, 1):
                print(f"  attempt {i}: {failure.cls.value}: {failure.detail[:200]}")
            return 1
        values = result.values
        print(f"[casesmith] model values={values} attempts={result.attempts}")
    else:
        print("[casesmith] 無 ModelSlot,跳過模型呼叫")

    # ⑤ renderer + ⑥ 契約檢查
    bundle_spec = CaseBundleSpec(
        case_id=case_id,
        title=f"Characterize {method['signature']['name']} current behaviour",
        suite_id=f"CASESMITH-{method['signature']['name'].upper()}",
    )
    files = render_bundle(
        bundle_spec, schema, base, case_row, values,
        verify_ignore=verify_ignore_for(domain, schema, case_row.table),
        ephemeral=args.ephemeral,
    )
    write_bundle(files, out_dir / "bundle")

    violations = check_test_case(
        yaml.safe_load(files[f"test_cases/{case_id}.yaml"])
    ) + check_suite_manifest(yaml.safe_load(files["suite_manifest.yaml"]))
    print(f"[casesmith] contract violations: {violations or 'none'}")
    print(f"[casesmith] bundle → {out_dir / 'bundle'}({len(files)} files)")
    return 0 if not violations else 1


if __name__ == "__main__":
    sys.exit(main())
