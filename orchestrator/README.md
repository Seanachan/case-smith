# orchestrator

Deterministic harness around a 7–8B model. The model only fills semantic
values (ModelSlot); structure, ordering, and formats are decided by code.

## Usage

```python
from orchestrator import Orchestrator, OpencodeClient, FakeClient, MetricsLog

# real model via opencode CLI (must be logged in; `opencode models` lists names)
orch = Orchestrator(
    OpencodeClient(model="opencode/big-pickle"),   # "provider/model" format
    metrics=MetricsLog("out/runs.jsonl"),          # optional; JSONL per attempt
)

# slots come from the planner (SeedPlanner(...).plan_case(...).slots)
result = orch.run_generate(
    case_id="Characterize_UpdateOrderStatus_Default",
    method_context="<code fragment injected by the caller>",
    slots=row.slots,
    validator=None,   # optional: callable(values) -> list[Failure] from downstream checks
)
result.values             # {"T_ORDER.STATUS_CD": "P", ...}
result.attempts           # 1 = first pass
result.template_version   # ties eval numbers to templates/generate.md version

# patch loop: replace exactly one field, deterministically applied in Python
patch = orch.run_patch(case_id, dict(result.values),
                       failure_detail="STATUS_CD mismatch vs golden master",
                       allowed_fields={s.name for s in row.slots})
from orchestrator import apply_patch
new_values = apply_patch(dict(result.values), patch)
```

Tests use `FakeClient([...])` (queued responses, records prompts) — no network.
End-to-end walkthrough: `docs/USAGE.md`; one-shot smoke: `scripts/e2e_smoke.py`.

## Modules

| module | responsibility | design decision it enforces |
|---|---|---|
| `client.py` | `ModelClient` protocol, `FakeClient`, `OpencodeClient` | transport pluggable; tests never hit network |
| `template.py` | versioned templates, fail-loud rendering | template version tied to eval numbers |
| `validate.py` | flat-JSON structural gate | structure guaranteed by code, not prompt |
| `classify.py` | SCHEMA / SQL_EXEC / SEMANTIC + `RetryPolicy` | classify before fixing |
| `core.py` | generate & patch flows, retry ladder, `apply_patch` | patch = single field, Python replaces |
| `metrics.py` | JSONL per-attempt log + summary | v1→vN improvement curve |

## Contracts

- The slot contract `ModelSlot` is owned by the planner
  (`pipeline/seed_planner.py`); this package imports it. `as_prompt_fact()`
  is the only thing the model ever sees about a slot.
- The caller injects `method_context` as a string. The model is never asked
  to read files — 7–8B models routinely skip such steps.
- Downstream checks (SQL execution, trust gates) feed back through
  `validator(values) -> list[Failure]` passed to `run_generate`.

## Failure classes

| class | meaning | response |
|---|---|---|
| SCHEMA | output shape wrong | strict reprompt (≤2 retries); real fix is constrained decoding |
| SQL_EXEC | fixture SQL failed | `PlannerBugError` immediately — retrying never helps |
| SEMANTIC | value implausible | retry once with few-shot examples from the slot |

## Transport

`OpencodeClient` shells out to `opencode run -m <provider/model> --pure`.
Flags verified against local `opencode run --help` (2026-08-05). Output is
plain stdout; `validate.py` extracts the first balanced JSON block, so
surrounding chatter is tolerated.

## Tests

    uv run python -m unittest discover -s orchestrator/tests -t . -v

Run from the repo root. Zero third-party dependencies.
