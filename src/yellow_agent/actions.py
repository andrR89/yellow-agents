"""High-level actions: each call does one meaningful thing and says why it stopped.

The MCP server and the agent loop call these same functions; the server only validates and
records. Design: docs/superpowers/specs/2026-11-06-actions-design.md.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from .emulator import DIRECTIONS, StepResult
from .state import SCREEN_COLS, GameState, Screen, ScreenKind
from .text import MORE_TEXT

STABLE_FRAMES = 30  # text with no ▼ that has not changed this long is waiting for A
BATTLE_STABLE_FRAMES = 150  # same in battle, past the pause of text that moves on by itself
# Free control only counts after this long with input enabled and nothing on screen changing:
# scripts pause with input enabled between parts (after Oak's catch: ~32 frames, measured).
QUIET_FRAMES = 90
TEXT_BOX_FIRST_ROW = 12  # dialogue / battle text box: rows 12-17 of the 20x18 screen
MAX_ADVANCE_FRAMES = 3000
MAX_WALK_TILES = 20
MAX_CURSOR_MOVES = 10
SETTLE_STABLE_FRAMES = 8  # after choosing: the next screen is drawn once tiles stop changing
SETTLE_MAX_FRAMES = 90
# A map script (Oak in the grass) locks input 1 frame after the step that triggers it
# (measured); walk looks a few frames past its last step so it can report `script`.
SCRIPT_CHECK_FRAMES = 4
A_RETRIES = 2  # choose: extra A presses when the menu did not react (session 4, move list)


class StopReason(StrEnum):
    MENU = "menu"  # a choice is on screen (cursor ▶)
    OVERWORLD = "overworld"  # the player has control again
    BATTLE_MENU = "battle_menu"  # FIGHT / PKMN / ITEM / RUN
    BLOCKED = "blocked"  # walk: something in the way
    WARPED = "warped"  # walk: the map changed
    TEXT = "text"  # walk: a text box opened
    SCRIPT = "script"  # walk: the game took control; its text comes a few frames later
    BATTLE = "battle"  # walk: a battle started
    DONE = "done"  # walk: all tiles walked; go_to: arrived
    NO_PATH = "no_path"  # go_to: no walkable way there (wall, out of the map, people)
    LIMIT = "limit"  # frame cap reached; the state says where we are


class ActionError(ValueError):
    """Invalid input, or the wrong screen for this action. Raised before pressing anything,
    except when a menu cursor does not move as expected (the message says so)."""


class ActionResult(BaseModel):
    action: dict[str, Any]
    stop: StopReason
    frames: int
    presses: int
    tiles: int | None = None  # walk only
    transcript: list[str] = Field(default_factory=list)
    state: GameState

    def extra(self) -> dict[str, Any]:
        """The fields a run step keeps next to the action and the state."""
        return self.model_dump(
            mode="json", include={"stop", "frames", "presses", "tiles", "transcript"}
        )


class Game(Protocol):
    """What the actions need from the emulator (Emulator implements it; tests fake it)."""

    @property
    def frame(self) -> int: ...
    def screen(self) -> Screen: ...
    def tile_map(self) -> list[int]: ...
    def state(self) -> GameState: ...
    def press(self, button: Any) -> None: ...
    def step(self, direction: Any) -> StepResult: ...
    def wait(self, frames: int) -> None: ...
    def input_enabled(self) -> bool: ...
    def in_battle(self) -> bool: ...
    def map_grid(self) -> Any: ...  # navigation.MapGrid


# -- pure helpers ---------------------------------------------------------------


def text_ready(tiles: list[int], stable_frames: int, in_battle: bool = False) -> bool:
    """A can be pressed: ▼ is in the text box, or the screen stopped changing.

    In battle most text without ▼ moves on by itself, and an A pressed 30 frames in landed on
    the battle menu that came next and picked FIGHT (session 4). Some battle text does wait for
    A with no ▼ ("PIKACHU grew to level 6!" and its stats box), so battle waits longer."""
    if MORE_TEXT in tiles[TEXT_BOX_FIRST_ROW * SCREEN_COLS :]:
        return True
    return stable_frames >= (BATTLE_STABLE_FRAMES if in_battle else STABLE_FRAMES)


def is_battle_menu(screen: Screen, in_battle: bool) -> bool:
    return (
        in_battle
        and screen.kind is ScreenKind.MENU
        and any("FIGHT" in line for line in screen.lines)
    )


def _position(screen: Screen, item: str) -> tuple[int, int] | None:
    """(row, column) of a menu item: a whole line (or box segment), else a word of a grid row."""
    item = item.strip().upper()
    for row, line in enumerate(screen.lines):
        if any(seg.strip().upper() == item for seg in line.split(" | ")):
            return row, 0
    for row, line in enumerate(screen.lines):
        words = line.upper().split()
        if item in words:
            return row, words.index(item)
    return None


def cursor_moves(screen: Screen, target: str) -> list[str]:
    """Directions that take the ▶ from the current item to `target`."""
    if screen.cursor is None:
        raise ActionError("no menu cursor on screen")
    there = _position(screen, target)
    if there is None:
        raise ActionError(f"{target!r} is not on screen; visible lines: {screen.lines}")
    here = _position(screen, screen.cursor)
    if here is None:
        raise ActionError(f"cannot place the cursor item {screen.cursor!r} on screen")
    dr, dc = there[0] - here[0], there[1] - here[1]
    vertical = ["down"] * dr if dr > 0 else ["up"] * -dr
    horizontal = ["right"] * dc if dc > 0 else ["left"] * -dc
    return vertical + horizontal


# -- text -----------------------------------------------------------------------


def _note(transcript: list[str], lines: list[str]) -> None:
    """Add lines not seen in the last few entries (text scrolls up one line at a time)."""
    for line in lines:
        if line not in transcript[-4:]:
            transcript.append(line)


def _advance(game: Game, max_frames: int) -> tuple[StopReason, int, list[str]]:
    """Press A whenever text is ready, until a choice, the battle menu, free control or the cap."""
    start = game.frame
    presses = 0
    transcript: list[str] = []
    prev: list[int] | None = None
    stable = 0
    while game.frame - start < max_frames:
        tiles = game.tile_map()
        stable = stable + 1 if tiles == prev else 0
        prev = tiles
        screen = game.screen()
        if screen.kind is ScreenKind.MENU:
            _note(transcript, screen.lines)
            if is_battle_menu(screen, game.in_battle()):
                return StopReason.BATTLE_MENU, presses, transcript
            return StopReason.MENU, presses, transcript
        if screen.kind is ScreenKind.TEXT:
            if stable == SETTLE_STABLE_FRAMES:
                _note(transcript, screen.lines)  # text that moves on by itself (battle)
            if text_ready(tiles, stable, game.in_battle()):
                _note(transcript, screen.lines)
                game.press("a")
                presses += 1
                prev, stable = None, 0
                continue
        elif game.input_enabled() and not game.in_battle() and stable >= QUIET_FRAMES:
            return StopReason.OVERWORLD, presses, transcript
        game.wait(1)
    return StopReason.LIMIT, presses, transcript


def _result(game: Game, action: dict[str, Any], start: int, stop: StopReason, presses: int,
            transcript: list[str], tiles: int | None = None) -> ActionResult:  # fmt: skip
    return ActionResult(
        action=action, stop=stop, frames=game.frame - start, presses=presses, tiles=tiles,
        transcript=transcript, state=game.state(),
    )  # fmt: skip


def advance_text(game: Game, max_frames: int = MAX_ADVANCE_FRAMES) -> ActionResult:
    """Advance dialogue until a choice, the battle menu or free control. Returns the transcript.

    Called on a quiet overworld, it waits QUIET_FRAMES for a scene to continue before saying
    `overworld`, so repeated calls get through script pauses."""
    action = {"tool": "advance_text"}
    start = game.frame
    # On a quiet overworld this waits QUIET_FRAMES for a scene to go on: some scripts leave
    # input looking free for hundreds of frames (the rival walking up to battle: ~300).
    stop, presses, transcript = _advance(game, max_frames)
    return _result(game, action, start, stop, presses, transcript)


def _require(game: Game, kind: ScreenKind, action: str) -> Screen:
    screen = game.screen()
    if screen.kind is not kind:
        hint = {ScreenKind.TEXT: "call advance_text", ScreenKind.MENU: "call choose"}
        raise ActionError(
            f"{action} needs the {kind.value} screen; it is {screen.kind.value}"
            + (f" ({hint[screen.kind]})" if screen.kind in hint else "")
        )
    return screen


def talk(game: Game) -> ActionResult:
    """Press A towards whatever the player faces and read what it says."""
    _require(game, ScreenKind.OVERWORLD, "talk")
    action = {"tool": "talk"}
    start = game.frame
    game.press("a")
    for _ in range(STABLE_FRAMES):
        if game.screen().kind is not ScreenKind.OVERWORLD or not game.input_enabled():
            break
        game.wait(1)
    else:
        return _result(game, action, start, StopReason.OVERWORLD, 1, [])
    stop, presses, transcript = _advance(game, MAX_ADVANCE_FRAMES)
    return _result(game, action, start, stop, presses + 1, transcript)


# -- walking --------------------------------------------------------------------


def validate_walk(direction: str, tiles: int) -> None:
    if direction not in DIRECTIONS:
        raise ActionError(f"invalid direction {direction!r}; expected one of {list(DIRECTIONS)}")
    if not 1 <= tiles <= MAX_WALK_TILES:
        raise ActionError(f"tiles must be 1-{MAX_WALK_TILES}")


def walk(game: Game, direction: str, tiles: int = 1) -> ActionResult:
    """Walk up to `tiles` tiles, stopping at the first thing that interrupts the walk."""
    validate_walk(direction, tiles)
    _require(game, ScreenKind.OVERWORLD, "walk")
    action = {"tool": "walk", "direction": direction, "tiles": tiles}
    start = game.frame
    moved = presses = 0
    stop = StopReason.DONE
    for _ in range(tiles):
        result = game.step(direction)
        presses += 1
        if result is StepResult.BLOCKED:
            stop = StopReason.BLOCKED
            break
        moved += 1
        if result is StepResult.WARPED:
            stop = StopReason.WARPED
            break
        if game.in_battle():
            stop = StopReason.BATTLE
            break
        if game.screen().kind is not ScreenKind.OVERWORLD:
            stop = StopReason.TEXT
            break
        if not game.input_enabled():
            stop = StopReason.SCRIPT
            break
    if stop in (StopReason.DONE, StopReason.BLOCKED):
        # A script that starts right after the last step, or that made the step be ignored.
        game.wait(SCRIPT_CHECK_FRAMES)
        if game.in_battle():
            stop = StopReason.BATTLE
        elif game.screen().kind is not ScreenKind.OVERWORLD:
            stop = StopReason.TEXT
        elif not game.input_enabled():
            stop = StopReason.SCRIPT
    return _result(game, action, start, stop, presses, [], tiles=moved)


# -- menus and battle -------------------------------------------------------------


def _settle(game: Game) -> None:
    """Wait until the screen stops changing (the next menu is drawn), at most SETTLE_MAX_FRAMES."""
    prev, stable = None, 0
    for _ in range(SETTLE_MAX_FRAMES):
        tiles = game.tile_map()
        stable = stable + 1 if tiles == prev else 0
        if stable >= SETTLE_STABLE_FRAMES:
            return
        prev = tiles
        game.wait(1)


def _choose(game: Game, item: str) -> tuple[StopReason, int, list[str]]:
    """Move the ▶ to `item` (closed loop), press A, then run the text that follows."""
    target = item.strip().upper()
    presses = 0
    for _ in range(MAX_CURSOR_MOVES + 1):
        screen = game.screen()
        here = _position(screen, screen.cursor) if screen.cursor else None
        if here is not None and here == _position(screen, target):
            break  # compare places, not text: the battle grid reads "FIGHT PKMN" under ▶
        moves = cursor_moves(screen, target)
        if not moves:
            raise ActionError(f"cursor is on {screen.cursor!r}, cannot reach {item!r}")
        game.press(moves[0])
        presses += 1
    else:
        raise ActionError(f"cursor did not reach {item!r} in {MAX_CURSOR_MOVES} moves")
    before = game.screen()
    for _ in range(1 + A_RETRIES):
        game.press("a")
        presses += 1
        _settle(game)
        if game.screen() != before:
            break  # an A pressed while the menu is still drawing is dropped: press again
    stop, more, transcript = _advance(game, MAX_ADVANCE_FRAMES)
    return stop, presses + more, transcript


def choose(game: Game, item: str) -> ActionResult:
    """Pick a menu item by name (YES / NO, FIGHT, a move, a start-menu entry)."""
    screen = _require(game, ScreenKind.MENU, "choose")
    cursor_moves(screen, item)  # validates that the item is on screen, before any press
    action = {"tool": "choose", "item": item}
    start = game.frame
    stop, presses, transcript = _choose(game, item)
    return _result(game, action, start, stop, presses, transcript)


def validate_slot(slot: int) -> None:
    if not 1 <= slot <= 4:
        raise ActionError("slot must be 1-4")


def use_move(game: Game, slot: int) -> ActionResult:
    """In battle: FIGHT, the move in `slot`, then the turn's messages until the next decision."""
    validate_slot(slot)
    state = game.state()
    on_main_menu = is_battle_menu(state.screen, game.in_battle())
    mon = state.battle.player_mon
    move_names = [m.name for m in mon.moves] if mon else []
    on_move_list = (
        game.in_battle()
        and state.screen.kind is ScreenKind.MENU
        and (state.screen.cursor or "") in move_names  # FIGHT already chosen (session 8)
    )
    if not (on_main_menu or on_move_list):
        raise ActionError("use_move needs the battle menu (FIGHT / PKMN / ITEM / RUN)")
    moves = mon.moves if mon else []
    if slot > len(moves):
        raise ActionError(f"no move in slot {slot}; moves: {[m.name for m in moves]}")
    move = moves[slot - 1]
    if move.pp == 0:
        raise ActionError(f"{move.name} has no PP left")
    action = {"tool": "use_move", "slot": slot, "move": move.name}
    start = game.frame
    if on_move_list:
        stop, presses, transcript = StopReason.MENU, 0, []
    else:
        stop, presses, transcript = _choose(game, "FIGHT")
    if stop is StopReason.MENU:  # the move list
        stop, more, rest = _choose(game, move.name)
        presses += more
        transcript += rest
    return _result(game, action, start, stop, presses, transcript)


# -- raw input, for anything the actions above do not cover ------------------------------

MAX_BUTTONS = 30
MAX_WAIT_FRAMES = 600
BUTTONS = ("a", "b", "start", "select", *DIRECTIONS)


def _screen_stop(game: Game) -> StopReason:
    screen = game.screen()
    if screen.kind is ScreenKind.MENU:
        return (
            StopReason.BATTLE_MENU if is_battle_menu(screen, game.in_battle()) else StopReason.MENU
        )
    if screen.kind is ScreenKind.TEXT:
        return StopReason.TEXT
    return StopReason.OVERWORLD if game.input_enabled() else StopReason.SCRIPT


def validate_buttons(buttons: list[str]) -> None:
    if not buttons or len(buttons) > MAX_BUTTONS:
        raise ActionError(f"pass 1-{MAX_BUTTONS} buttons")
    bad = [b for b in buttons if b not in BUTTONS]
    if bad:
        raise ActionError(f"invalid buttons: {bad}; valid: {list(BUTTONS)}")


def press_buttons(game: Game, buttons: list[str]) -> ActionResult:
    """Raw presses, in order. Directions walk one tile each outside menus."""
    validate_buttons(buttons)
    start = game.frame
    for b in buttons:
        game.press(b)
    action = {"tool": "press_buttons", "buttons": list(buttons)}
    return _result(game, action, start, _screen_stop(game), len(buttons), [])


def wait(game: Game, frames: int = 60) -> ActionResult:
    """Let the game run without input."""
    if not 1 <= frames <= MAX_WAIT_FRAMES:
        raise ActionError(f"frames must be 1-{MAX_WAIT_FRAMES}")
    start = game.frame
    game.wait(frames)
    return _result(game, {"tool": "wait", "frames": frames}, start, _screen_stop(game), 0, [])


# -- go_to: A* on the map's collision grid (navigation.py) --------------------------------

MAX_REPLANS = 3  # someone stepped into the path: plan again
MAX_COORD = 255


def validate_go_to(x: Any, y: Any) -> tuple[int, int]:
    try:
        xi, yi = int(x), int(y)
    except (TypeError, ValueError):
        raise ActionError("x and y must be integers") from None
    if not (0 <= xi <= MAX_COORD and 0 <= yi <= MAX_COORD):
        raise ActionError(f"x and y must be 0-{MAX_COORD}")
    return xi, yi


def _exit_step(grid: Any, goal: tuple[int, int]) -> str | None:
    """A door on the map's border (house mats, the lab's exit) needs one more step outward."""
    x, y = goal
    on_warp = any(e.kind == "warp" and (e.x, e.y) == goal for e in grid.exits)
    if not on_warp:
        return None
    if y == grid.height - 1:
        return "down"
    if y == 0:
        return "up"
    if x == 0:
        return "left"
    if x == grid.width - 1:
        return "right"
    return None


def go_to(game: Game, x: Any, y: Any) -> ActionResult:
    """Walk to (x, y) on the current map along the shortest walkable path.

    Stops like walk (warped, text, script, battle). A door on the map's border is walked
    through. `no_path`: the cell is a wall, outside the map or unreachable."""
    from .navigation import find_path

    goal = validate_go_to(x, y)
    _require(game, ScreenKind.OVERWORLD, "go_to")
    action = {"tool": "go_to", "x": goal[0], "y": goal[1]}
    start = game.frame
    moved = presses = 0
    stop = StopReason.DONE
    for _ in range(MAX_REPLANS + 1):
        s = game.state()
        here = (s.x, s.y)
        grid = game.map_grid()
        path = find_path(grid, here, goal)
        if path is None:
            stop = StopReason.NO_PATH
            break
        if not path:
            break
        replan = False
        for direction in path:
            result = game.step(direction)
            presses += 1
            if result is StepResult.BLOCKED:
                if not game.input_enabled():
                    stop = StopReason.SCRIPT
                    return _result(game, action, start, stop, presses, [], tiles=moved)
                replan = True  # someone moved into the way
                break
            moved += 1
            if result is StepResult.WARPED:
                return _result(game, action, start, StopReason.WARPED, presses, [], tiles=moved)
            if game.in_battle():
                return _result(game, action, start, StopReason.BATTLE, presses, [], tiles=moved)
            if game.screen().kind is not ScreenKind.OVERWORLD:
                return _result(game, action, start, StopReason.TEXT, presses, [], tiles=moved)
            if not game.input_enabled():
                return _result(game, action, start, StopReason.SCRIPT, presses, [], tiles=moved)
        if not replan:
            break
    else:
        stop = StopReason.BLOCKED
    if stop is StopReason.DONE:
        s = game.state()
        if (s.x, s.y) != goal:
            stop = StopReason.BLOCKED
        elif (out := _exit_step(game.map_grid(), goal)) is not None:
            result = game.step(out)
            presses += 1
            if result is StepResult.WARPED:
                stop = StopReason.WARPED
    if stop in (StopReason.DONE, StopReason.BLOCKED):
        game.wait(SCRIPT_CHECK_FRAMES)  # a script that starts right after the last step
        if game.in_battle():
            stop = StopReason.BATTLE
        elif game.screen().kind is not ScreenKind.OVERWORLD:
            stop = StopReason.TEXT
        elif not game.input_enabled():
            stop = StopReason.SCRIPT
    return _result(game, action, start, stop, presses, [], tiles=moved)
