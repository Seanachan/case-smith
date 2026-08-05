"""Orchestrator: renders templates, calls the model, validates output,
classifies failures, retries per policy, logs metrics.

Principle: knowledge is INJECTED into the prompt by the caller
(method_context, slot facts). The model is never told to go read a file —
7-8B models routinely skip such steps.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pipeline.seed_planner import ModelSlot

from .classify import Failure, FailureClass, PlannerBugError, RetryPolicy
from .client import ModelClient
from .metrics import MetricsLog
from .template import load_template, render
from .validate import SchemaError, parse_flat_json, validate_patch

_STRICT_REMINDER = (
    "\nSTRICT FORMAT REMINDER: previous output was rejected ({detail}). "
    "Output ONLY one flat JSON object with exactly the listed keys. "
    "No markdown, no explanations."
)


class GenerationFailed(Exception):
    """Retry budget exhausted; carries per-attempt failure records."""

    def __init__(self, message: str, attempts: list):
        super().__init__(message)
        self.attempts = attempts


@dataclass
class GenerateResult:
    values: dict
    attempts: int
    template_version: str


class Orchestrator:
    def __init__(self, client: ModelClient, template_dir=None,
                 metrics: MetricsLog | None = None,
                 policy: RetryPolicy | None = None):
        self.client = client
        self.template_dir = (Path(template_dir) if template_dir
                             else Path(__file__).parent / "templates")
        self.metrics = metrics
        self.policy = policy or RetryPolicy()

    # -- generate ---------------------------------------------------------

    def run_generate(self, case_id: str, method_context: str,
                     slots: list[ModelSlot], validator=None) -> GenerateResult:
        """validator: callable(values) -> list[Failure], fed by downstream
        checks (SQL execution, trust gates). SQL_EXEC aborts immediately —
        that is a planner bug, not a model problem."""
        template = load_template(self.template_dir / "generate.md")
        retries = {FailureClass.SCHEMA: 0, FailureClass.SEMANTIC: 0}
        failures: list = []
        attempt = 0
        strict_suffix = ""
        fewshot = ""
        while True:
            attempt += 1
            prompt = render(template, {
                "case_name": case_id,
                "method_context": method_context,
                "slot_facts": "\n".join(s.as_prompt_fact() for s in slots),
                "output_keys": json.dumps([s.name for s in slots]),
                "fewshot_block": fewshot,
            }) + strict_suffix
            raw = self.client.generate(prompt)
            try:
                values = parse_flat_json(raw, slots)
            except SchemaError as exc:
                failures.append(Failure(FailureClass.SCHEMA, str(exc)))
                self._record(case_id, template.version, attempt, "schema")
                if self.policy.allows(FailureClass.SCHEMA,
                                      retries[FailureClass.SCHEMA]):
                    retries[FailureClass.SCHEMA] += 1
                    strict_suffix = _STRICT_REMINDER.format(detail=exc)
                    continue
                raise GenerationFailed(
                    f"{case_id}: schema retries exhausted", failures) from exc

            ext = list(validator(values)) if validator else []
            sql = [f for f in ext if f.cls is FailureClass.SQL_EXEC]
            if sql:
                self._record(case_id, template.version, attempt, "sql_exec")
                raise PlannerBugError(
                    f"{case_id}: fixture SQL failed ({sql[0].detail}). "
                    "Fix the planner; retrying never helps for this class.")
            sem = [f for f in ext if f.cls is FailureClass.SEMANTIC]
            if sem:
                failures.append(sem[0])
                self._record(case_id, template.version, attempt, "semantic")
                if self.policy.allows(FailureClass.SEMANTIC,
                                      retries[FailureClass.SEMANTIC]):
                    retries[FailureClass.SEMANTIC] += 1
                    fewshot = self._fewshot_block(slots)
                    continue
                raise GenerationFailed(
                    f"{case_id}: semantic retries exhausted", failures)

            self._record(case_id, template.version, attempt, "pass")
            return GenerateResult(values=values, attempts=attempt,
                                  template_version=template.version)

    @staticmethod
    def _fewshot_block(slots: list[ModelSlot]) -> str:
        lines = [f"{s.name}: {' | '.join(s.examples)}"
                 for s in slots if s.examples]
        if not lines:
            return ""
        return "Known-good example values:\n" + "\n".join(lines)

    # -- patch ------------------------------------------------------------

    def run_patch(self, case_id: str, artifact: dict, failure_detail: str,
                  allowed_fields: set) -> dict:
        """Model returns exactly {"field", "value"}; replacement is done in
        Python by apply_patch, never by regenerating the artifact."""
        template = load_template(self.template_dir / "patch.md")
        retries = 0
        failures: list = []
        attempt = 0
        strict_suffix = ""
        while True:
            attempt += 1
            prompt = render(template, {
                "artifact_excerpt": json.dumps(artifact, indent=2),
                "failure_detail": failure_detail,
                "allowed_fields": json.dumps(sorted(allowed_fields)),
            }) + strict_suffix
            raw = self.client.generate(prompt)
            try:
                patch = validate_patch(raw, allowed_fields)
            except SchemaError as exc:
                failures.append(Failure(FailureClass.SCHEMA, str(exc)))
                self._record(case_id, template.version, attempt, "schema")
                if self.policy.allows(FailureClass.SCHEMA, retries):
                    retries += 1
                    strict_suffix = _STRICT_REMINDER.format(detail=exc)
                    continue
                raise GenerationFailed(
                    f"{case_id}: patch retries exhausted", failures) from exc
            self._record(case_id, template.version, attempt, "pass")
            return patch

    def _record(self, case_id, version, attempt, outcome):
        if self.metrics:
            self.metrics.record(case_id, version, attempt, outcome)


def apply_patch(artifact: dict, patch: dict) -> dict:
    """Pure function: new dict with exactly one field replaced."""
    if patch["field"] not in artifact:
        raise KeyError(patch["field"])
    new = dict(artifact)
    new[patch["field"]] = patch["value"]
    return new
