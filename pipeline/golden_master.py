"""Golden master capture:從 ARTF run 的 db_query evidence 抓現況,重生 verify SQL。

流程定位(見 docs/REQ_BLOCK_TRACING.md「執行拓撲」):

    recording run:seed →(SUT,等 shell_command runtime)→ snapshot 查詢
      → evidence 的 masked_sample_result = 現況整列
    capture(本工具):現況 → verify SQL(觀測值釘進 WHERE;ignore 與被遮罩
      欄位除外)→ 覆寫 bundle 的 queries/verify_<case>.sql
    replay run:重生的 verify = 回歸測試——特徵化「現況」,非「正確」
    (Characterize_ 命名的本意)。expected 全程來自觀測,模型不參與。

用法:
    uv run python -m pipeline.golden_master \
        --run-dir <ARTF 的 RUN-... 目錄> \
        --bundle out/xxx/bundle \
        --schema schema/schema.example.json \
        --case Characterize_XXX --table T_ORDER \
        [--domain domain/xxx.yaml] [--op read_case_row]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

from pipeline.render_artifacts import render_verify_sql, verify_ignore_for
from pipeline.seed_planner import DomainConfig, Schema, SeedRow

# JdbcProviderRuntime 對 password/secret/token 類欄名的遮罩值
_MASK_MARKERS = {"***", "***MASKED***"}


def load_query_evidence(path: Path) -> dict:
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("evidence_type") != "query_evidence":
        raise ValueError(f"{path}: 不是 query_evidence(evidence_type={doc.get('evidence_type')!r})")
    return doc


def observed_row(evidence: dict) -> Tuple[Dict, List[str]]:
    """取 snapshot 的第一列(per-case 一列的模型)。回 (row, 被遮罩而剔除的欄)。"""
    rows = evidence.get("masked_sample_result") or []
    if not rows:
        raise ValueError(
            f"masked_sample_result 為空(row_count={evidence.get('row_count')})——"
            "現況無列可抓;檢查 snapshot 查詢與 seed 是否成功")
    row = dict(rows[0])
    dropped = [k for k, v in row.items() if isinstance(v, str) and v in _MASK_MARKERS]
    for key in dropped:
        row.pop(key)
    return row, dropped


def rebuild_verify(schema: Schema, table: str, row: Dict, ignore=frozenset()) -> str:
    """觀測列 → verify SQL。借 render_verify_sql:塞進假 SeedRow,scope 標 golden。"""
    return render_verify_sql(
        schema, SeedRow(table=table, scope="golden_master", values=dict(row)), ignore
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pipeline.golden_master")
    ap.add_argument("--run-dir", required=True, help="ARTF 的 RUN-... 目錄")
    ap.add_argument("--bundle", required=True, help="要覆寫 verify 的 bundle 目錄")
    ap.add_argument("--schema", required=True)
    ap.add_argument("--case", required=True, help="test_case_id(對應 verify_<case>.sql)")
    ap.add_argument("--table", required=True, help="case 主表(verify 目標)")
    ap.add_argument("--domain", help="domain YAML(取 ignore_in_snapshot)")
    ap.add_argument("--op", default="read_case_row", help="snapshot 的 execute op id")
    args = ap.parse_args(argv)

    import json
    schema = Schema.from_json(json.loads(Path(args.schema).read_text(encoding="utf-8")))
    domain = DomainConfig.from_yaml(args.domain) if args.domain else DomainConfig()

    evidence_path = Path(args.run_dir) / "provider-evidence" / "jdbc" / f"query_{args.op}.yaml"
    evidence = load_query_evidence(evidence_path)
    row, dropped = observed_row(evidence)
    print(f"[golden-master] observed({args.table}): {row}")
    if dropped:
        print(f"[golden-master] 遮罩欄位不進 verify: {dropped}")

    ignore = verify_ignore_for(domain, schema, args.table)
    sql = rebuild_verify(schema, args.table, row, ignore)
    target = Path(args.bundle) / "queries" / f"verify_{args.case}.sql"
    old = target.read_text(encoding="utf-8") if target.exists() else "(無)"
    target.write_text(sql, encoding="utf-8")
    print(f"[golden-master] rewrote {target}")
    print("--- old ---\n" + old + "--- new ---\n" + sql)
    return 0


if __name__ == "__main__":
    sys.exit(main())
