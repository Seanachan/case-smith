"""CaseSmith 總指揮 CLI:spec.json + schema.json → ARTF bundle,一條指令。

單方法模式:
    uv run python -m pipeline.cli \
        --spec   extractors/spec_card.example.json \
        --schema schema/schema.example.json \
        --domain domain/domain.example.yaml \
        --method GetActiveCustomer \
        --model  opencode/big-pickle \
        --out    out/demo

block 模式(--method 換成 --block,其餘同):
    uv run python -m pipeline.cli --spec ... --schema ... \
        --block blocks/settlement.yaml --out out/settlement

    # block.yaml 形狀(見 docs/REQ_BLOCK_TRACING.md):
    #   block_id: OrderSettlement
    #   description: >  自然語言行為描述(給人;也當語意 context 注入)
    #   anchors:
    #     - function: SettleOrder
    #     - file: Billing/Settle.vb
    #       lines: 120-180

    # 只列出 spec 裡有哪些方法可選:
    uv run python -m pipeline.cli --spec ... --schema ... --list

串接順序(全部確定性,模型只在 ④ 填值):
① 挑方法 / block 錨點沿 calls 閉包 → ② condition_columns 過濾成 ask_model
白名單(排除 PK/FK——ID 歸 planner 配,不問模型)→ ③ planner 出
SeedPlan+slots → ④ orchestrator 問模型 → ⑤ renderer 出 bundle → ⑥ 契約檢查。
block 模式另落地 coverage.md(對照 block 描述找落差,REQ 的驗收機制)。
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
from pipeline.block_spec import BlockSpec, build_block_spec, coverage_report
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


def _filter_ask_model(condition_columns, schema: Schema) -> list:
    """condition_columns → ask_model:排除 PK/FK(ID 歸 planner),排除 schema 查無的欄。"""
    whitelist = []
    for key in condition_columns:
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


def _block_context(block_def: dict, block: BlockSpec) -> str:
    """block 描述(人寫的語意)+ 閉包事實,注入模型當 context。"""
    tables = "; ".join(
        f"{t} ({'/'.join(sorted(ops))})" for t, ops in sorted(block.tables.items())
    )
    lines = [f"Block: {block_def['block_id']}"]
    desc = (block_def.get("description") or "").strip()
    if desc:
        lines.append(desc)
    lines.append(f"Methods in scope: {len(block.method_ids)}")
    lines.append(f"Tables touched: {tables or 'none'}")
    if block.condition_columns:
        lines.append("Condition columns: " + ", ".join(block.condition_columns))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="casesmith", description=__doc__)
    ap.add_argument("--spec", required=True, help="extractor 產的 spec card JSON")
    ap.add_argument("--schema", required=True, help="schema JSON(契約形狀見 schema.example.json)")
    ap.add_argument("--domain", help="domain config YAML(選填,空 config 也能跑)")
    ap.add_argument("--method", help="方法名或完整 id(與 --block 二選一)")
    ap.add_argument("--block", help="block.yaml 路徑(錨點+描述;與 --method 二選一)")
    ap.add_argument("--model", default="opencode/big-pickle", help="opencode 的 provider/model")
    ap.add_argument("--out", default="out/casesmith", help="bundle 輸出目錄")
    ap.add_argument("--list", action="store_true", help="列出 spec 裡的方法後結束")
    ap.add_argument("--fake", help='測試用:跳過真模型,直接給 JSON 值,如 \'{"T_X.COL": "V"}\'')
    args = ap.parse_args(argv)

    spec_card = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    schema = Schema.from_json(json.loads(Path(args.schema).read_text(encoding="utf-8")))

    if args.list:
        for m in spec_card["methods"]:
            cols = ", ".join(m.get("condition_columns", [])) or "-"
            print(f"{m['signature']['name']:30s} {m['id']}  [{cols}]")
        return 0
    if bool(args.method) == bool(args.block):
        ap.error("--method 與 --block 恰選其一(或用 --list)")

    domain = DomainConfig.from_yaml(args.domain) if args.domain else DomainConfig()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.block:
        block_def = yaml.safe_load(Path(args.block).read_text(encoding="utf-8"))
        block = build_block_spec(spec_card, block_def["block_id"], block_def["anchors"])
        if block.anchor_misses:
            print(f"[casesmith] !! 錨點沒中(檢查 block.yaml):{block.anchor_misses}")
        if not block.method_ids:
            raise SystemExit("block 閉包為空:所有錨點都沒中")
        known = [t for t in sorted(block.tables) if t in schema.tables]
        unknown = sorted(set(block.tables) - set(known))
        if unknown:
            print(f"[casesmith] !! block 觸及但 schema 查無的表(不進 seed):{unknown}")
        if not known:
            raise SystemExit("block 觸及的表在 schema 全查無,無 seed 可產")
        (out_dir / "coverage.md").write_text(coverage_report(block), encoding="utf-8")
        print(f"[casesmith] block={block_def['block_id']} "
              f"methods={len(block.method_ids)} coverage → {out_dir / 'coverage.md'}")
        tables = known
        ask_model = _filter_ask_model(block.condition_columns, schema)
        name = block_def["block_id"]
        context = _block_context(block_def, block)
    else:
        method = _pick_method(spec_card, args.method)
        tables = [t["name"] for t in method.get("tables", [])]
        if not tables:
            raise SystemExit(f"{args.method}: spec 裡沒有觸及任何表,無 seed 可產")
        ask_model = _filter_ask_model(method.get("condition_columns", []), schema)
        name = method["signature"]["name"]
        context = _method_context(method)
        print(f"[casesmith] method={method['id']}")

    case_id = f"Characterize_{name}_Default"
    print(f"[casesmith] tables={tables} ask_model={ask_model or '(無——全部欄位由 planner 填)'}")

    # ③ planner。case 主表:第一個 ask_model 欄位所屬表,否則表清單第一個
    planner = SeedPlanner(schema, domain, ask_model=ask_model)
    base = planner.plan_base(tables)
    primary = ask_model[0].partition(".")[0] if ask_model else tables[0]
    case_row = planner.plan_case(primary, case_id)

    # ④ orchestrator(有 slot 才問模型)
    values: dict = {}
    if case_row.slots:
        if args.fake is not None:
            client = FakeClient([args.fake])
        else:
            client = OpencodeClient(model=args.model)
        orch = Orchestrator(client, metrics=MetricsLog(out_dir / "runs.jsonl"))
        try:
            result = orch.run_generate(case_id, context, case_row.slots)
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
        title=f"Characterize {name} current behaviour",
        suite_id=f"CASESMITH-{name.upper()}",
    )
    files = render_bundle(
        bundle_spec, schema, base, case_row, values,
        verify_ignore=verify_ignore_for(domain, schema, case_row.table),
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
