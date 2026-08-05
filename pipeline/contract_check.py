"""契約檢查器:rendered artifact 對 vendored ARTF v0.2 契約檔驗證。

注意:schema/framework/*.v0.2.schema.yaml **不是** JSON Schema draft,
是「規則清單」型契約(required_sections / prohibited_sections / data_rules
/ block 行為),所以這裡是規則驅動的自寫檢查,不是 jsonschema.validate。
規則檔 vendored 進 repo,框架更新時重抓,檢查邏輯不用改。

prohibited_execution_artifact_keys(sql / query / fixture / payload ...)
的語意是「禁止內嵌原始內容」:官方 sample 的 verify check 本身就有
`query: {ref: ...}` key,所以只有當值是**原始字串**(非 ref/value 包裝的
mapping)才算違規。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

import yaml

FRAMEWORK_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema" / "framework"

# 來源:ARTF docs/02-architecture/06_artifact_contracts.md:872(查證記錄見
# docs/ARTF_CONTRACT.md Q1);契約檔本身未列 enum,故 vendored 在此。
STATUS_ENUM = {"draft_skeleton", "draft_executable", "active", "needs_update", "retired"}

# suite_manifest 已棄用的 artifact_roots(schemas/suite_manifest.v0.2:43)
DEPRECATED_ROOTS = {"execution_profiles", "environment_bindings"}


def load_contract(name: str) -> dict:
    path = FRAMEWORK_SCHEMA_DIR / f"{name}.v0.2.schema.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _resolve_path(doc: Any, tokens: List[str], prefix: str, violations: List[str]) -> None:
    """走 dotted path;`<xxx>` token = 萬用字元(該層每個 value 都要往下滿足)。"""
    if not tokens:
        return
    head, rest = tokens[0], tokens[1:]
    if not isinstance(doc, dict):
        violations.append(f"required section 缺失: {prefix}{head}(上層不是 mapping)")
        return
    if head.startswith("<") and head.endswith(">"):
        if not doc:
            violations.append(f"required section 缺失: {prefix}{head}(空 mapping)")
            return
        for key, value in doc.items():
            _resolve_path(value, rest, f"{prefix}{key}.", violations)
        return
    if head not in doc:
        violations.append(f"required section 缺失: {prefix}{head}")
        return
    _resolve_path(doc[head], rest, f"{prefix}{head}.", violations)


def _scan_raw_artifact_keys(node: Any, banned: set, where: str, violations: List[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in banned and not isinstance(value, dict):
                violations.append(
                    f"{where}: 內嵌原始 execution artifact key {key!r}(值必須走 ref 間接引用)"
                )
            _scan_raw_artifact_keys(value, banned, where, violations)
    elif isinstance(node, list):
        for item in node:
            _scan_raw_artifact_keys(item, banned, where, violations)


def check_test_case(doc: dict, contract: dict | None = None) -> List[str]:
    contract = contract or load_contract("test_case_dsl")
    violations: List[str] = []

    supported = set(contract["version_compatibility"]["supported_versions"])
    if doc.get("dsl_version") not in supported:
        violations.append(f"dsl_version {doc.get('dsl_version')!r} 不在 {sorted(supported)}")

    for section in contract["required_sections"]:
        _resolve_path(doc, section.split("."), "", violations)

    for key in contract["prohibited_sections"]:
        if key in doc:
            violations.append(f"prohibited section 出現在頂層: {key}")

    if doc.get("status") not in STATUS_ENUM:
        violations.append(f"status {doc.get('status')!r} 不在 {sorted(STATUS_ENUM)}")

    data_rules = contract.get("data_rules", {})
    source_fields = set(data_rules.get("source_fields", ["ref", "value"]))
    for name, entry in (doc.get("data") or {}).items():
        if not isinstance(entry, dict) or len(source_fields & set(entry)) != 1:
            violations.append(f"data.{name}: 必須恰有 {sorted(source_fields)} 其中之一")

    banned = set(contract.get("source_ref_rules", {}).get(
        "prohibited_execution_artifact_keys", []))
    for part in ("setup", "execute", "verify", "cleanup"):
        if part in doc:
            _scan_raw_artifact_keys(doc[part], banned, part, violations)

    return violations


def check_suite_manifest(doc: dict, contract: dict | None = None) -> List[str]:
    contract = contract or load_contract("suite_manifest")
    violations: List[str] = []

    if doc.get("contract_version") != "v0.2":
        violations.append(f"contract_version {doc.get('contract_version')!r} != v0.2")
    for key in ("suite_id", "selection"):
        if key not in doc:
            violations.append(f"required section 缺失: {key}")
    if not doc.get("tests"):
        violations.append("tests 為空:test_case 不會被 runner 發現(suite 是唯一登錄點)")

    roots = doc.get("artifact_roots") or {}
    for required_root in ("provider_instances", "env_profiles"):
        if required_root not in roots:
            violations.append(f"artifact_roots 缺 canonical 根目錄: {required_root}")
    for deprecated in DEPRECATED_ROOTS & set(roots):
        violations.append(f"artifact_roots 含已棄用根目錄: {deprecated}")

    return violations
