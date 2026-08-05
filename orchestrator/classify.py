"""Failure taxonomy.

Classification decides the response; mixing classes fixes the wrong thing.
SCHEMA -> stricter reprompt (real fix: constrained decoding).
SQL_EXEC -> planner bug; retrying never helps.
SEMANTIC -> retry with few-shot examples.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class FailureClass(enum.Enum):
    SCHEMA = "schema"
    SQL_EXEC = "sql_exec"
    SEMANTIC = "semantic"


@dataclass
class Failure:
    cls: FailureClass
    detail: str


@dataclass
class RetryPolicy:
    """Max retries per failure class (attempts = 1 + retries)."""

    limits: dict = field(default_factory=lambda: {
        FailureClass.SCHEMA: 2,
        FailureClass.SEMANTIC: 1,
        FailureClass.SQL_EXEC: 0,
    })

    def allows(self, cls: FailureClass, retries_used: int) -> bool:
        return retries_used < self.limits.get(cls, 0)


class PlannerBugError(Exception):
    """Fixture SQL failed to execute: fix the planner; retrying never helps."""
