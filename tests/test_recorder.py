"""Run recording: every step of a run must be replayable on the site."""

from __future__ import annotations

import json

import pytest

from yellow_agent.recorder import RunRecorder, RunStep, load_run
from yellow_agent.state import Battle, BattleKind, GameState, Screen, ScreenKind

PNG = b"\x89PNG\r\n\x1a\nfake"


def _state(x: int) -> GameState:
    return GameState(
        player_name="YELLOW",
        rival_name="BLUE",
        map_id=0,
        map_name="PALLET_TOWN",
        x=x,
        y=6,
        facing="down",
        money=3000,
        badges=[],
        pikachu_happiness=90,
        pikachu_mood=0,
        party=[],
        battle=Battle(kind=BattleKind.NONE),
        screen=Screen(kind=ScreenKind.OVERWORLD, lines=[]),
    )


def test_roundtrip(tmp_path):
    rec = RunRecorder.start(tmp_path, source="mcp", start_state="got_pikachu", run_id="r1")
    rec.record(
        frame=1200,
        state=_state(5),
        action={"tool": "press_buttons", "buttons": ["down"]},
        screenshot_png=PNG,
        model="claude:claude-sonnet-5-5",
        prompt="state: ...",
        response="I will go down.",
        input_tokens=812,
        output_tokens=40,
        latency_ms=950.5,
        cost_usd=0.0031,
    )
    rec.record(frame=1224, state=_state(6), action={"tool": "wait", "frames": 24})

    header, steps = load_run(tmp_path / "r1")
    assert header.run_id == "r1"
    assert header.source == "mcp"
    assert header.start_state == "got_pikachu"
    assert [s.index for s in steps] == [0, 1]
    first, second = steps
    assert isinstance(first, RunStep)
    assert first.state.x == 5 and first.frame == 1200
    assert first.screenshot == "screens/000000.png"
    assert (tmp_path / "r1" / first.screenshot).read_bytes() == PNG
    assert (first.input_tokens, first.output_tokens) == (812, 40)
    assert second.screenshot is None and second.model is None


def test_every_line_is_standalone_json(tmp_path):
    rec = RunRecorder.start(tmp_path, source="agent", run_id="r2")
    rec.record(frame=0, state=_state(1), action={"tool": "press_buttons", "buttons": ["a"]})
    lines = (tmp_path / "r2" / "run.jsonl").read_text().splitlines()
    assert [json.loads(line)["type"] for line in lines] == ["header", "step"]


@pytest.mark.parametrize("bad", ["../x", "a/b", ""])
def test_run_id_cannot_escape_runs_dir(tmp_path, bad):
    with pytest.raises(ValueError):
        RunRecorder.start(tmp_path, source="mcp", run_id=bad)
