"""End-to-end checks against the real game. Need YELLOW_ROM; skipped otherwise."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from yellow_agent.emulator import Emulator, StepResult
from yellow_agent.newgame import new_game
from yellow_agent.state import ScreenKind

pytestmark = pytest.mark.rom

ROOT = Path(__file__).resolve().parent.parent
SYM = os.environ.get("YELLOW_SYM", str(ROOT / "data/generated/pokeyellow.sym"))
DATA = os.environ.get("YELLOW_DATA", str(ROOT / "data/generated"))

# Bedroom -> stairs -> living room -> front door -> Pallet Town, measured on a fresh game.
# (direction, expected result, expected (map, x, y) afterwards)
ROUTE: list[tuple[str, StepResult, tuple[str, int, int]]] = [
    ("left", StepResult.MOVED, ("REDS_HOUSE_2F", 2, 6)),
    ("left", StepResult.MOVED, ("REDS_HOUSE_2F", 1, 6)),
    ("left", StepResult.BLOCKED, ("REDS_HOUSE_2F", 1, 6)),
    ("up", StepResult.MOVED, ("REDS_HOUSE_2F", 1, 5)),
    ("up", StepResult.MOVED, ("REDS_HOUSE_2F", 1, 4)),
    ("up", StepResult.MOVED, ("REDS_HOUSE_2F", 1, 3)),
    ("up", StepResult.MOVED, ("REDS_HOUSE_2F", 1, 2)),
    *[("right", StepResult.MOVED, ("REDS_HOUSE_2F", x, 2)) for x in range(2, 8)],
    ("up", StepResult.WARPED, ("REDS_HOUSE_1F", 7, 1)),
    *[("down", StepResult.MOVED, ("REDS_HOUSE_1F", 7, y)) for y in range(2, 7)],
    *[("left", StepResult.MOVED, ("REDS_HOUSE_1F", x, 6)) for x in range(6, 2, -1)],
    ("down", StepResult.MOVED, ("REDS_HOUSE_1F", 3, 7)),
    ("down", StepResult.WARPED, ("PALLET_TOWN", 5, 6)),
    ("down", StepResult.MOVED, ("PALLET_TOWN", 5, 7)),
    *[("right", StepResult.MOVED, ("PALLET_TOWN", x, 7)) for x in range(6, 11)],
    *[("up", StepResult.MOVED, ("PALLET_TOWN", 10, y)) for y in range(6, 0, -1)],
]


@pytest.fixture(scope="module")
def emu():
    e = Emulator(os.environ["YELLOW_ROM"], sym=SYM, data_dir=DATA)
    new_game(e)
    yield e
    e.close()


def test_new_game_lands_in_bedroom(emu):
    s = emu.state()
    assert (s.player_name, s.rival_name) == ("YELLOW", "BLUE")
    assert (s.map_name, s.x, s.y, s.facing) == ("REDS_HOUSE_2F", 3, 6, "up")
    assert s.party == []


def test_one_press_is_one_tile_from_bedroom_to_pallet_town(emu):
    for i, (direction, result, (map_name, x, y)) in enumerate(ROUTE):
        got = emu.step(direction)
        s = emu.state()
        assert (got, s.map_name, s.x, s.y) == (result, map_name, x, y), f"step {i}: {direction}"
        assert s.facing == direction
        assert s.screen.kind is ScreenKind.OVERWORLD


def test_screenshots_do_not_advance_the_game(tmp_path):
    runs = []
    for with_screens in (False, True):
        e = Emulator(os.environ["YELLOW_ROM"], sym=SYM, data_dir=DATA)
        new_game(e)
        for direction, *_ in ROUTE[:10]:
            e.step(direction)
            if with_screens:
                assert e.screenshot_png().startswith(b"\x89PNG")
        runs.append((e.frame, e.state()))
        e.close()
    assert runs[0] == runs[1]


def test_new_game_types_custom_names():
    e = Emulator(os.environ["YELLOW_ROM"], sym=SYM, data_dir=DATA)
    new_game(e, player_name="CLAUDE", rival_name="GEMINI")
    s = e.state()
    e.close()
    assert (s.player_name, s.rival_name, s.map_name) == ("CLAUDE", "GEMINI", "REDS_HOUSE_2F")
    assert s.screen.kind is ScreenKind.OVERWORLD


def test_baseline_route_is_the_tested_route():
    from yellow_agent.baseline import HOUSE_TO_NORTH_EXIT

    assert [direction for direction, *_ in ROUTE] == HOUSE_TO_NORTH_EXIT


def test_actions_alone_reach_pikachu():
    from yellow_agent.action_route import play_to_pikachu_with_actions

    e = Emulator(os.environ["YELLOW_ROM"], sym=SYM, data_dir=DATA)
    try:
        route = play_to_pikachu_with_actions(e)
    finally:
        e.close()
    last = route.results[-1].state
    assert [m.species for m in last.party] == ["PIKACHU"]
    assert last.screen.kind is ScreenKind.OVERWORLD
    assert route.calls <= 40, route.calls  # session 3 needed 107


def test_walk_into_a_wall_is_blocked():
    from yellow_agent.actions import StopReason, walk

    e = Emulator(os.environ["YELLOW_ROM"], sym=SYM, data_dir=DATA)
    try:
        new_game(e)
        r = walk(e, "left", 3)  # bedroom (3,6): wall after 2 tiles
    finally:
        e.close()
    assert (r.stop, r.tiles) == (StopReason.BLOCKED, 2)
