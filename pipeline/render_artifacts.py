"""Renderer:SeedPlan + 模型值 → ARTF v0.2 artifact bundle。

輸出檔案形狀以 schema/framework/*.v0.2.schema.yaml 契約與 ARTF 官方 sample
(samples/20-provider-capability-p0/data/jdbc)為準,查證細節見
docs/ARTF_CONTRACT.md。一個 bundle 至少含:

    test_cases/<case_id>.yaml     DSL 本體
    suite_manifest.yaml           唯一的 case 登錄點(runner 只認 suite)
    provider_instances/*.yaml     jdbc provider 宣告
    env_profiles/*.yaml           環境值(連線字串只准走這層的 bindings)
    fixtures/*.sql                seed(base + per-case)與 cleanup
    queries/*.sql                 verify 查詢(欄位驗證寫進 WHERE)
    expected_results/*.json       db_record_exists 的期望(min_rows)

原則(CLAUDE.md):結構、命名、順序全部在這裡硬編碼;模型值只出現在
seed / verify SQL 的字面值。ARTF 的 DB 驗證是 row_count/存在性比對,
不是 snapshot diff——要驗欄位值就得寫進 verify SQL 的 WHERE,
ignore 欄位 = 不寫進 WHERE(docs/ARTF_CONTRACT.md Q5)。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, Mapping

import yaml

from pipeline.seed_planner import DomainConfig, Schema, SeedPlan, SeedRow, emit_sql

ID_START = 900000
ID_END = 999999


@dataclass(frozen=True)
class CaseBundleSpec:
    case_id: str
    title: str
    suite_id: str
    provider_id: str = "casesmith-db"
    target: str = "db"
    profile: str = "local_fake"
    db_schema: str = "APP"


# ---------------------------------------------------------------------------
# SQL 片段
# ---------------------------------------------------------------------------


def _sql_literal(value: Any) -> str:
    """DB2 字面值(verify WHERE 用;seed SQL 走 emit_sql 自己的 formatter)。"""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, Decimal)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def apply_model_values(case_row: SeedRow, model_values: Mapping[str, Any]) -> SeedRow:
    """模型值覆蓋 planner 預留值(單欄位 patch 的套用點)。回傳新 SeedRow。"""
    values = dict(case_row.values)
    for slot in case_row.slots:
        if slot.name in model_values:
            values[slot.column] = model_values[slot.name]
    return SeedRow(
        table=case_row.table, scope=case_row.scope,
        values=values, slots=list(case_row.slots),
    )


def render_ddl(schema: Schema, tables_parent_first: Iterable[str]) -> str:
    """確定性 DDL:CREATE SCHEMA + CREATE TABLE(無 FK)+ 全部 FK 走 ALTER。

    給 ephemeral(框架自管 H2)bootstrap 用——H2 起來是空的,DDL 必須在
    seed 之前跑。FK 一律 ALTER 後補:表都建完才加約束,環自然無事。
    `IF NOT EXISTS` 是 H2 語法;這份 DDL 只用於 ephemeral,不打真 DB2。
    identity 欄位未處理(example schema 無;接真 schema 時補)。
    """
    tables = [schema.tables[t] for t in tables_parent_first]
    stmts: list = []
    for schema_name in sorted({t.schema_name for t in tables if t.schema_name}):
        stmts.append(f"CREATE SCHEMA IF NOT EXISTS {schema_name};")
    for table in tables:
        cols = []
        for col in table.columns:
            line = f"    {col.name} {col.type}"
            if not col.nullable:
                line += " NOT NULL"
            cols.append(line)
        if table.primary_key:
            cols.append(f"    PRIMARY KEY ({', '.join(table.primary_key)})")
        stmts.append(
            f"CREATE TABLE IF NOT EXISTS {table.qualified_name} (\n"
            + ",\n".join(cols) + "\n);"
        )
    for table in tables:
        for fk in table.foreign_keys:
            ref = schema.tables[fk.ref_table]
            stmts.append(
                f"ALTER TABLE {table.qualified_name} ADD CONSTRAINT {fk.name} "
                f"FOREIGN KEY ({', '.join(fk.columns)}) "
                f"REFERENCES {ref.qualified_name} ({', '.join(fk.ref_columns)});"
            )
    return "\n".join(stmts) + "\n"


def verify_ignore_for(domain: DomainConfig, schema: Schema, table: str) -> FrozenSet[str]:
    """domain 的 ignore_in_snapshot("TABLE.COL" 精確或 fnmatch 樣式)→
    該表要從 verify WHERE 排除的欄名集合。

    落地語意(ARTF_CONTRACT.md Q5):框架沒有欄位級 ignore 機制,
    「忽略」= 該欄不寫進 verify SQL 的 WHERE。對實際欄位逐一比對,
    比對不到的樣式是 no-op(不報錯——跨專案 config 可含他表欄位)。
    """
    ignored = set()
    for col in schema.tables[table].columns:
        key = f"{table}.{col.name}"
        if any(fnmatch(key, pat) for pat in domain.ignore_in_snapshot):
            ignored.add(col.name)
    return frozenset(ignored)


def render_verify_sql(
    schema: Schema, case_row: SeedRow, ignore: FrozenSet[str] = frozenset()
) -> str:
    """欄位值驗證寫進 WHERE;ignore(易變欄位)= 不寫進 WHERE。"""
    table = schema.tables[case_row.table]
    if len(table.primary_key) != 1:
        raise ValueError(f"{case_row.table} 無單欄主鍵,verify SQL 無法定位列")
    pk = table.primary_key[0]
    conds = [f"{pk} = {_sql_literal(case_row.values[pk])}"]
    for col, val in case_row.values.items():
        if col == pk or col in ignore or val is None:
            continue
        conds.append(f"{col} = {_sql_literal(val)}")
    return (
        f"SELECT {pk} FROM {table.qualified_name}\n"
        + "WHERE " + "\n  AND ".join(conds) + "\n"
    )


def render_cleanup_sql(schema: Schema, tables_parent_first: Iterable[str]) -> str:
    """反 topo 順序 DELETE(子表先),鎖定保留 ID 區間,不碰區間外資料。"""
    out = []
    for t in reversed(list(tables_parent_first)):
        table = schema.tables[t]
        if len(table.primary_key) != 1:
            continue  # 無單欄 PK 的表不在自動 cleanup 範圍(與 planner 同限制)
        pk = table.primary_key[0]
        out.append(
            f"DELETE FROM {table.qualified_name} WHERE {pk} BETWEEN {ID_START} AND {ID_END};"
        )
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# YAML 文件(dict 組裝,safe_dump 輸出;key 順序 = 樣本順序)
# ---------------------------------------------------------------------------


def _test_case_doc(spec: CaseBundleSpec, ephemeral: bool = False) -> dict:
    tc, tgt = spec.case_id, spec.target
    ev = f"provider-evidence/jdbc"
    doc = {
        "dsl_version": "v0.2",
        "test_case_id": tc,
        "title": spec.title,
        # Characterize_ 命名 = 記錄現況;產生器產物先標 draft_executable,
        # 人審後才升 active(status enum 見 contract_check.STATUS_ENUM)
        "status": "draft_executable",
        "revision": 1,
        "labels": {"generator": "casesmith"},
        "compatible_profiles": [spec.profile],
        "targets": {tgt: {"provider_id": spec.provider_id}},
        "data": {
            "seed_base": {"ref": "fixtures/seed_base.sql"},
            "seed_case": {"ref": f"fixtures/seed_{tc}.sql"},
            "cleanup_sql": {"ref": "fixtures/cleanup.sql"},
            "verify_query": {"ref": f"queries/verify_{tc}.sql"},
        },
        "setup": {
            "operations": [
                {
                    "id": "seed_base",
                    "target": tgt,
                    "operation": "db_seed",
                    "inputs": {"sql_ref": {"ref": "${data.seed_base}"}},
                },
                {
                    "id": "seed_case",
                    "target": tgt,
                    "operation": "db_seed",
                    "inputs": {"sql_ref": {"ref": "${data.seed_case}"}},
                },
            ]
        },
        # E2E 假件版:execute = 查詢 case 列(之後換成 shell_command 跑 .exe)
        "execute": {
            "operations": [
                {
                    "id": "read_case_row",
                    "target": tgt,
                    "operation": "db_query",
                    "inputs": {"query_ref": {"ref": "${data.verify_query}"}},
                    "outputs": {
                        "row_count": "row_count",
                        "sample_rows": "sample_rows",
                        "duration_ms": "duration_ms",
                        "query_evidence_ref": "query_evidence_ref",
                    },
                }
            ]
        },
        "verify": {
            "checks": [
                {
                    "id": "case_row_matches",
                    "type": "db_record_exists",
                    "target": tgt,
                    "query": {"ref": f"queries/verify_{tc}.sql"},
                    "expected_ref": "expected_results/verify_expected.json",
                    "options": {"timeout": "PT20S", "poll_interval": "PT2S"},
                }
            ]
        },
        "cleanup": {
            "operations": [
                {
                    "id": "cleanup_all",
                    "target": tgt,
                    "operation": "db_cleanup",
                    "inputs": {"sql_ref": {"ref": "${data.cleanup_sql}"}},
                }
            ]
        },
        "evidence": {
            "required": [
                f"{ev}/seed_{tc}__seed_base.yaml",
                f"{ev}/seed_{tc}__seed_case.yaml",
                f"{ev}/query_{tc}__read_case_row.yaml",
                f"{ev}/cleanup_{tc}__cleanup_all.yaml",
            ]
        },
        "runtime": {"timeout": "PT1M", "retry": {"max_attempts": 1}},
    }
    if ephemeral:
        # H2 ephemeral 起來是空庫:DDL bootstrap 必須排在所有 seed 之前
        doc["data"]["ddl_bootstrap"] = {"ref": "fixtures/ddl_bootstrap.sql"}
        doc["setup"]["operations"].insert(0, {
            "id": "bootstrap_ddl",
            "target": tgt,
            "operation": "db_seed",
            "inputs": {"sql_ref": {"ref": "${data.ddl_bootstrap}"}},
        })
        doc["evidence"]["required"].insert(0, f"{ev}/seed_{tc}__bootstrap_ddl.yaml")
    return doc


def _suite_manifest_doc(spec: CaseBundleSpec) -> dict:
    return {
        "contract_version": "v0.2",
        "suite_id": spec.suite_id,
        "purpose": "CaseSmith generated characterization suite.",
        "profile": spec.profile,
        "profiles": [],
        "selection": {"mode": "suite", "suite": spec.suite_id},
        "tests": [f"test_cases/{spec.case_id}.yaml"],
        "artifact_roots": {
            "provider_instances": "provider_instances/",
            "env_profiles": "env_profiles/",
            "expected_results": "expected_results/",
            "fixtures": "fixtures/",
            "queries": "queries/",
        },
        "evidence_policy": {
            # 沿用官方 sample 的 enum 值(未查到完整 enum 清單,見 ARTF_CONTRACT.md)
            "evidence_classification": "framework_provider_capability_only",
            "downstream_release_evidence": False,
        },
    }


def _provider_instance_doc(spec: CaseBundleSpec) -> dict:
    return {
        "provider_instance_version": "v0.2",
        "provider_id": spec.provider_id,
        "provider_type": "jdbc",
        "runtime_modes": ["native", "ephemeral"],
        "defaults": {"query_timeout": "PT10S", "strict_params": True},
        "operations": {
            "db_seed": {"outputs": ["affected_rows", "duration_ms", "seed_evidence_ref"]},
            "db_query": {
                "outputs": ["row_count", "sample_rows", "duration_ms", "query_evidence_ref"]
            },
            "db_record_exists": {
                "outputs": ["matched", "row_count", "duration_ms", "query_evidence_ref"]
            },
            "db_cleanup": {
                "outputs": ["affected_rows", "duration_ms", "cleanup_evidence_ref"]
            },
        },
        "evidence": {
            "capture": [
                "query_ref", "sql_ref", "dialect", "masked_params", "row_count",
                "duration_ms", "masked_sample_result", "affected_rows", "status",
            ],
            "redact": ["connection", "password", "secret", "token"],
        },
        "failure_mapping": {
            "record_not_found": "ASSERTION_FAILED",
            "cleanup_failed": "CLEANUP_FAILED",
        },
        "labels": {"dialect_family": "db2"},
    }


def _env_profile_doc(spec: CaseBundleSpec, ephemeral: bool = False) -> dict:
    if ephemeral:
        # 框架自管 H2(DB2 相容模式)——免 Docker、免環境變數。
        # local_ref 只認 approved_local_h2_oracle / approved_local_h2_db2
        # (ContractBaselineService.approvedJdbcLocalRef,實碼查證)
        connection = {"local_ref": "approved_local_h2_db2"}
        runtime_mode = "ephemeral"
    else:
        connection = {"secret_ref": "env://JDBC_CONNECTION"}
        runtime_mode = "native"
    return {
        "env_profile_id": spec.profile,
        "execution_mode": "local",
        "isolation_scope": "per_run",
        "dependency_policy": {
            "require_readiness_evidence": False,
            "allow_framework_managed_dependencies": True,
        },
        "data_policy": {
            "approved_expected_results_required": False,
            "production_data_allowed": False,
            "generated_data_allowed": True,
            "secrets_must_use_refs": True,
        },
        "providers": {
            spec.provider_id: {
                "runtime_mode": runtime_mode,
                "bindings": {
                    # 連線字串只准放這層,且必須走 secret_ref(不放 raw 值)
                    "connection": connection,
                    "dialect": "db2",
                    "schema": spec.db_schema,
                    "strict_params": True,
                    "query_timeout": "PT10S",
                },
            }
        },
    }


# ---------------------------------------------------------------------------
# bundle 組裝
# ---------------------------------------------------------------------------


def render_bundle(
    spec: CaseBundleSpec,
    schema: Schema,
    base_plan: SeedPlan,
    case_row: SeedRow,
    model_values: Mapping[str, Any],
    verify_ignore: FrozenSet[str] = frozenset(),
    ephemeral: bool = False,
) -> Dict[str, str]:
    """回傳 {相對路徑: 檔案內容}。純函式,不落地;落地用 write_bundle。

    ephemeral=True:bundle 針對框架自管 H2(免 Docker/環境變數)——
    多一份 DDL bootstrap、env_profile 走 generated:// 連線。
    """
    patched = apply_model_values(case_row, model_values)
    case_plan = SeedPlan(order=[patched.table], deferred=[], rows=[patched])
    all_tables = list(base_plan.order)
    if patched.table not in all_tables:
        all_tables.append(patched.table)

    def _yaml(doc: dict) -> str:
        return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)

    tc = spec.case_id
    files = {
        "fixtures/seed_base.sql": emit_sql(base_plan, schema) + "\n",
        f"fixtures/seed_{tc}.sql": emit_sql(case_plan, schema) + "\n",
        "fixtures/cleanup.sql": render_cleanup_sql(schema, all_tables),
        f"queries/verify_{tc}.sql": render_verify_sql(schema, patched, verify_ignore),
        "expected_results/verify_expected.json": json.dumps({"min_rows": 1}) + "\n",
        f"test_cases/{tc}.yaml": _yaml(_test_case_doc(spec, ephemeral=ephemeral)),
        "suite_manifest.yaml": _yaml(_suite_manifest_doc(spec)),
        f"provider_instances/{spec.provider_id}.yaml": _yaml(_provider_instance_doc(spec)),
        f"env_profiles/{spec.profile}.yaml": _yaml(_env_profile_doc(spec, ephemeral=ephemeral)),
    }
    if ephemeral:
        files["fixtures/ddl_bootstrap.sql"] = render_ddl(schema, all_tables)
    return files


def write_bundle(files: Mapping[str, str], out_dir: Path) -> None:
    for rel, content in files.items():
        path = Path(out_dir) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
