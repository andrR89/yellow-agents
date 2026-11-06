"""Run recording format: one JSONL file per run, plus screenshots.

Every run (an MCP session, our own agent loop, an eval scenario) is recorded the same way, so
the site can replay any of them: game screen on one side, what the agent saw and decided on the
other.

Layout::

    runs/<run_id>/
        run.jsonl            line 1: {"type": "header", ...}; then one {"type": "step", ...}
        screens/000000.png   screenshot taken after step 0 (optional per step)

Lines are appended and flushed as they happen, so a crashed run is still readable.
"""

from __future__ import annotations

import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .state import GameState

FORMAT_VERSION = 1
_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

Source = Literal["mcp", "agent", "eval"]


class RunHeader(BaseModel):
    type: Literal["header"] = "header"
    format_version: int = FORMAT_VERSION
    run_id: str
    source: Source  # who was playing: an MCP client, our agent loop, or an eval scenario
    started_at: datetime
    start_state: str | None = None  # save state the run started from
    git_commit: str | None = None
    notes: str | None = None


class RunStep(BaseModel):
    type: Literal["step"] = "step"
    index: int
    frame: int  # emulator frame after the action; the deterministic clock
    time: datetime
    state: GameState  # state after the action
    action: dict[str, Any]  # e.g. {"tool": "press_buttons", "buttons": ["up"]}
    screenshot: str | None = None  # path relative to the run dir
    # What the model saw and said. Empty when the decision was not made by our loop
    # (e.g. Claude Code over MCP: the client keeps the prompt, we only see the tool call).
    model: str | None = None
    prompt: str | None = None
    response: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float | None = None  # model latency, not emulator time
    cost_usd: float = 0.0
    extra: dict[str, Any] = Field(default_factory=dict)


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


class RunRecorder:
    def __init__(self, run_dir: Path, header: RunHeader):
        self.run_dir = run_dir
        self.header = header
        self._index = 0
        self._file = (run_dir / "run.jsonl").open("a", encoding="utf-8")

    @classmethod
    def start(
        cls,
        runs_dir: str | Path,
        *,
        source: Source,
        start_state: str | None = None,
        run_id: str | None = None,
        notes: str | None = None,
    ) -> RunRecorder:
        now = datetime.now(UTC)
        if run_id is None:
            run_id = now.strftime("%Y%m%d-%H%M%S")
        if not _RUN_ID.match(run_id):
            raise ValueError("run id must match [A-Za-z0-9_-]{1,64}")
        run_dir = Path(runs_dir) / run_id
        (run_dir / "screens").mkdir(parents=True, exist_ok=False)
        header = RunHeader(
            run_id=run_id,
            source=source,
            started_at=now,
            start_state=start_state,
            git_commit=_git_commit(),
            notes=notes,
        )
        rec = cls(run_dir, header)
        rec._write(header)
        return rec

    def _write(self, line: BaseModel) -> None:
        self._file.write(line.model_dump_json() + "\n")
        self._file.flush()

    def record(
        self,
        *,
        frame: int,
        state: GameState,
        action: dict[str, Any],
        screenshot_png: bytes | None = None,
        **model_fields: Any,
    ) -> RunStep:
        screenshot = None
        if screenshot_png is not None:
            screenshot = f"screens/{self._index:06d}.png"
            (self.run_dir / screenshot).write_bytes(screenshot_png)
        step = RunStep(
            index=self._index,
            frame=frame,
            time=datetime.now(UTC),
            state=state,
            action=action,
            screenshot=screenshot,
            **model_fields,
        )
        self._write(step)
        self._index += 1
        return step

    def close(self) -> None:
        self._file.close()


def load_run(run_dir: str | Path) -> tuple[RunHeader, list[RunStep]]:
    lines = (Path(run_dir) / "run.jsonl").read_text(encoding="utf-8").splitlines()
    header = RunHeader.model_validate_json(lines[0])
    steps = [RunStep.model_validate_json(line) for line in lines[1:] if line.strip()]
    return header, steps
