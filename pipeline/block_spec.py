"""Block 層級 spec:錨點 → 呼叫圖 transitive closure → 聯集 + coverage 報告。

需求脈絡見 docs/REQ_BLOCK_TRACING.md:輸入單位是 block(一段業務),
事前不知道它碰哪些表/服務;extractor 給 per-method 事實,這裡從錨點
沿呼叫圖追出全貌。

spec card v2 契約:methods[] 各多一個 `"calls": ["<被呼叫方法名>", ...]`
(語法層抽取,C# extractor 吐)。v1 卡片沒有 calls 欄位 → 視為無邊,
閉包 = 錨點本身(向後相容)。

錨點形狀(block.yaml 的 anchors,由 block.md 經開發期強模型+人審轉出):
    {"function": "SettleOrder"}                # 方法名或 id 尾綴
    {"file": "Billing/Settle.vb", "lines": "120-180"}   # lines 選填

解析原則(全部確定性):
- 錨點多重匹配 → 全部進閉包(保守放大,coverage 報告揭露)。
- callee 名字解析不到 spec 內任何方法 → 記進 unresolved_calls
  (外部/框架呼叫),不猜。
- 錨點完全沒中 → 記進 anchor_misses,不吞。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set


@dataclass
class BlockSpec:
    block_id: str
    method_ids: List[str]                 # 閉包內全部方法(id,穩定排序)
    tables: Dict[str, Set[str]]           # 表名 -> 操作聯集(SELECT/INSERT/...)
    condition_columns: List[str]          # ask_model 候選(聯集,排序)
    endpoints: List[dict]                 # endpoint 物件聯集(去重)
    unresolved_calls: List[str]           # 解析不到的被呼叫名(排序)
    anchor_misses: List[dict] = field(default_factory=list)  # 沒中的錨點原文


def _parse_lines(spec: str) -> tuple:
    lo, _, hi = str(spec).partition("-")
    return int(lo), int(hi or lo)


def resolve_anchor(spec_card: dict, anchor: dict) -> List[dict]:
    """一個錨點 → 匹配的方法清單(可多個;空 = miss,由呼叫端記)。"""
    methods = spec_card["methods"]
    if "function" in anchor:
        name = anchor["function"]
        return [
            m for m in methods
            if m["signature"]["name"] == name or m["id"] == name
            or m["id"].endswith("." + name)
        ]
    if "file" in anchor:
        hits = [m for m in methods if m["file"] == anchor["file"]]
        if "lines" in anchor:
            lo, hi = _parse_lines(anchor["lines"])
            hits = [m for m in hits if lo <= m["line"] <= hi]
        return hits
    raise ValueError(f"錨點缺 function/file 欄位: {anchor!r}")


def build_block_spec(spec_card: dict, block_id: str, anchors: List[dict]) -> BlockSpec:
    """anchors → BFS 閉包(沿 calls 邊)→ 聚合。純函式,不碰檔案。"""
    by_name: Dict[str, List[dict]] = {}
    for m in spec_card["methods"]:
        by_name.setdefault(m["signature"]["name"], []).append(m)

    seed: List[dict] = []
    misses: List[dict] = []
    for anchor in anchors:
        hits = resolve_anchor(spec_card, anchor)
        if hits:
            seed.extend(hits)
        else:
            misses.append(anchor)

    visited: Dict[str, dict] = {}
    unresolved: Set[str] = set()
    stack = list(seed)
    while stack:
        m = stack.pop()
        if m["id"] in visited:
            continue
        visited[m["id"]] = m
        for callee in m.get("calls", []):
            targets = by_name.get(callee)
            if not targets:
                # 名字帶點時再試 id 尾綴(如 "Dao.OrderRepository.Save")
                targets = [x for x in spec_card["methods"]
                           if x["id"].endswith("." + callee)]
            if targets:
                stack.extend(targets)
            else:
                unresolved.add(callee)

    tables: Dict[str, Set[str]] = {}
    cond_cols: Set[str] = set()
    endpoints: List[dict] = []
    seen_ep: Set[str] = set()
    for m in visited.values():
        for t in m.get("tables", []):
            tables.setdefault(t["name"], set()).update(t.get("operations", []))
        cond_cols.update(m.get("condition_columns", []))
        for ep in m.get("endpoints", []):
            key = repr(sorted(ep.items()))
            if key not in seen_ep:
                seen_ep.add(key)
                endpoints.append(ep)

    return BlockSpec(
        block_id=block_id,
        method_ids=sorted(visited),
        tables=tables,
        condition_columns=sorted(cond_cols),
        endpoints=endpoints,
        unresolved_calls=sorted(unresolved),
        anchor_misses=misses,
    )


def coverage_report(block: BlockSpec) -> str:
    """人讀的 coverage 報告:對照 block.md 描述找落差用(REQ 的驗收機制)。"""
    lines = [f"# Block coverage: {block.block_id}", ""]
    lines.append(f"方法({len(block.method_ids)}):")
    lines += [f"  - {mid}" for mid in block.method_ids]
    lines.append(f"表({len(block.tables)}):")
    lines += [f"  - {t} [{'/'.join(sorted(ops))}]"
              for t, ops in sorted(block.tables.items())]
    lines.append(f"條件欄位(ask_model 候選,{len(block.condition_columns)}):")
    lines += [f"  - {c}" for c in block.condition_columns]
    lines.append(f"endpoints({len(block.endpoints)}):")
    lines += [f"  - {ep}" for ep in block.endpoints]
    if block.unresolved_calls:
        lines.append(f"解析不到的呼叫({len(block.unresolved_calls)})——外部/框架,或 extractor 沒掃到:")
        lines += [f"  - {c}" for c in block.unresolved_calls]
    if block.anchor_misses:
        lines.append(f"!! 沒中的錨點({len(block.anchor_misses)})——檢查 block.yaml:")
        lines += [f"  - {a}" for a in block.anchor_misses]
    return "\n".join(lines) + "\n"
