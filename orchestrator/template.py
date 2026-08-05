"""Versioned prompt templates with fail-loud placeholder substitution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_VERSION_RE = re.compile(r"<!--\s*version:\s*(\S+)\s*-->")
_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


@dataclass
class Template:
    version: str
    text: str

    @property
    def placeholders(self) -> set[str]:
        return set(_PLACEHOLDER_RE.findall(self.text))


def load_template(path: Path) -> Template:
    text = Path(path).read_text(encoding="utf-8")
    first_line = text.splitlines()[0] if text else ""
    match = _VERSION_RE.search(first_line)
    if not match:
        raise ValueError(f"{path}: first line must be '<!-- version: vN -->'")
    return Template(version=match.group(1), text=text)


def render(template: Template, mapping: dict) -> str:
    missing = template.placeholders - mapping.keys()
    if missing:
        raise KeyError(f"missing placeholder values: {sorted(missing)}")
    return _PLACEHOLDER_RE.sub(lambda m: str(mapping[m.group(1)]), template.text)
