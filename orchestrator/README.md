# orchestrator

Deterministic harness around a 7–8B model. The model only fills semantic
values (ModelSlot); structure, ordering, and formats are decided by code.

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
