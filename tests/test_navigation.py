"""Collision grid and A*, plus go_to on a fake game that really walks a grid. No ROM."""

from __future__ import annotations

import pytest

from yellow_agent.actions import ActionError, StopReason, go_to, validate_go_to
from yellow_agent.emulator import StepResult
from yellow_agent.navigation import (
    DIRECTIONS,
    Exit,
    MapGrid,
    Person,
    find_path,
    read_collision_list,
    runs,
    walkable_cells,
)
from yellow_agent.state import Battle, BattleKind, GameState, Screen, ScreenKind


def grid_from(rows: list[str], exits=(), people=()) -> MapGrid:
    return MapGrid(width=len(rows[0]), height=len(rows),
                   walkable=[[c != "#" for c in r] for r in rows],
                   exits=list(exits), people=list(people))  # fmt: skip


def test_walkable_cells_use_each_cells_bottom_left_tile():
    # One block (2x2 cells). Tiles 0-15 row-major; bottom-left of each cell: 4, 6, 12, 14.
    tiles = {0: list(range(16))}
    grid = walkable_cells(lambda bx, by: 0, 1, 1, lambda b, i: tiles[b][i], passable={4, 14})
    assert grid == [[True, False], [False, True]]


def test_collision_list_stops_at_ff():
    mem = {0x100: 0x10, 0x101: 0x20, 0x102: 0xFF, 0x103: 0x30}
    assert read_collision_list(mem.__getitem__, 0x100) == {0x10, 0x20}


ROOM = [
    "#######",
    "#.....#",
    "#.###.#",
    "#.....#",
    "###.###",
]


def test_a_star_goes_around_walls():
    path = find_path(grid_from(ROOM), (1, 1), (5, 3))
    assert len(path) == 6  # 4 right + 2 down, or 2 down + 4 right: both shortest


def test_no_path_into_a_wall_or_off_the_map():
    g = grid_from(ROOM)
    assert find_path(g, (1, 1), (3, 2)) is None
    assert find_path(g, (1, 1), (40, 40)) is None
    assert find_path(g, (1, 1), (1, 1)) == []


def test_people_block_except_on_the_goal():
    g = grid_from(["#####", "#...#", "#####"], people=[Person(x=2, y=1, who="person")])
    assert find_path(g, (1, 1), (3, 1)) is None
    assert find_path(g, (1, 1), (2, 1)) == ["right"]


def test_runs():
    assert runs(["up", "up", "left", "up"]) == [("up", 2), ("left", 1), ("up", 1)]


class GridGame:
    """Walks a MapGrid for real: step() moves the player when the next cell is free."""

    def __init__(self, rows, pos, exits=(), people=(), on_enter=None):
        self.grid = grid_from(rows, exits, people)
        self.x, self.y = pos
        self.frame = 0
        self.pressed: list[str] = []
        self.map = "ROOM"
        self.kind = ScreenKind.OVERWORLD
        self.on_enter = on_enter or {}  # (x, y) -> "text" | "warp"

    def step(self, d):
        self.pressed.append(d)
        self.frame += 17
        dx, dy = DIRECTIONS[d]
        nx, ny = self.x + dx, self.y + dy
        if not (0 <= nx < self.grid.width and 0 <= ny < self.grid.height):
            self.map = "OUTSIDE"
            return StepResult.WARPED
        if not self.grid.free(nx, ny):
            return StepResult.BLOCKED
        self.x, self.y = nx, ny
        event = self.on_enter.get((nx, ny))
        if event == "text":
            self.kind = ScreenKind.TEXT
        return StepResult.MOVED

    def map_grid(self):
        return self.grid

    def screen(self):
        return Screen(kind=self.kind, lines=["Hey!"] if self.kind is ScreenKind.TEXT else [])

    def input_enabled(self):
        return True

    def in_battle(self):
        return False

    def wait(self, n):
        self.frame += n

    def tile_map(self):
        return []

    def press(self, b):
        self.pressed.append(b)

    def state(self):
        return GameState(player_name="CLAUDE", rival_name="GEMINI", map_id=0, map_name=self.map,
                         x=self.x, y=self.y, facing="up", money=0, badges=[],
                         pikachu_happiness=0, pikachu_mood=0, party=[],
                         battle=Battle(kind=BattleKind.NONE), screen=self.screen())  # fmt: skip


def test_go_to_walks_the_path_and_arrives():
    game = GridGame(ROOM, (1, 1))
    r = go_to(game, 5, 3)
    assert (r.stop, (game.x, game.y), r.tiles) == (StopReason.DONE, (5, 3), 6)


def test_go_to_walks_out_through_a_door_on_the_border():
    game = GridGame(ROOM, (1, 1), exits=[Exit(kind="warp", to="outside", x=3, y=4)])
    r = go_to(game, 3, 4)
    assert r.stop is StopReason.WARPED and game.pressed[-1] == "down"


def test_go_to_reports_no_path():
    game = GridGame(ROOM, (1, 1))
    r = go_to(game, 3, 2)
    assert r.stop is StopReason.NO_PATH and game.pressed == []


def test_go_to_replans_when_someone_steps_in():
    rows = ["#######", "#.....#", "#.....#", "#######"]
    game = GridGame(rows, (1, 1))
    real_step = game.step
    blocked_once = []

    def step(d):
        if not blocked_once and (game.x, game.y) == (2, 1):  # a person appears ahead, once
            blocked_once.append(1)
            game.grid.people.append(Person(x=3, y=1, who="person"))
            return StepResult.BLOCKED
        return real_step(d)

    game.step = step
    r = go_to(game, 5, 1)
    assert r.stop is StopReason.DONE and (game.x, game.y) == (5, 1)


def test_go_to_stops_when_a_text_box_opens():
    game = GridGame(ROOM, (1, 1), on_enter={(3, 1): "text"})
    r = go_to(game, 5, 1)
    assert r.stop is StopReason.TEXT and (game.x, game.y) == (3, 1)


@pytest.mark.parametrize("x, y", [("a", 1), (1, None), (-1, 0), (256, 0)])
def test_go_to_validates(x, y):
    with pytest.raises(ActionError):
        validate_go_to(x, y)
