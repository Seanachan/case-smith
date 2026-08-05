"""Model transport. The orchestrator depends only on the ModelClient protocol."""

from __future__ import annotations

import subprocess
from typing import Protocol


class ModelClient(Protocol):
    def generate(self, prompt: str) -> str: ...


class FakeClient:
    """Test double: returns queued responses in order, records prompts."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._responses:
            raise RuntimeError("FakeClient: no responses left")
        return self._responses.pop(0)


class OpencodeClient:
    """`opencode run` CLI transport (non-interactive).

    Flags verified against local `opencode run --help` (2026-08-05):
    -m/--model takes "provider/model"; --agent selects an agent profile;
    --pure disables external plugins. Output is captured from stdout as
    plain text — downstream validation extracts the JSON block, so
    surrounding formatting is tolerated.
    """

    def __init__(self, model: str, agent: str | None = None,
                 timeout: float = 300.0, extra_args: tuple = ()):
        self.model = model  # e.g. "ollama/qwen2.5-coder:7b"
        self.agent = agent
        self.timeout = timeout
        self.extra_args = tuple(extra_args)

    def generate(self, prompt: str) -> str:
        cmd = ["opencode", "run", "--model", self.model, "--pure"]
        if self.agent:
            cmd += ["--agent", self.agent]
        cmd += list(self.extra_args)
        cmd.append(prompt)
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=self.timeout)
        if proc.returncode != 0:
            raise RuntimeError(
                f"opencode exited {proc.returncode}: {proc.stderr.strip()[:500]}")
        return proc.stdout
