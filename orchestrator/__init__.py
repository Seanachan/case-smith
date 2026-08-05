"""CaseSmith orchestrator: deterministic harness around a 7-8B model."""

from pipeline.seed_planner import ModelSlot

from .classify import Failure, FailureClass, PlannerBugError, RetryPolicy
from .client import FakeClient, ModelClient, OpencodeClient
from .core import GenerateResult, GenerationFailed, Orchestrator, apply_patch
from .metrics import MetricsLog
from .validate import SchemaError

__all__ = [
    "Failure", "FailureClass", "PlannerBugError", "RetryPolicy",
    "FakeClient", "ModelClient", "OpencodeClient",
    "GenerateResult", "GenerationFailed", "Orchestrator", "apply_patch",
    "MetricsLog", "ModelSlot", "SchemaError",
]
