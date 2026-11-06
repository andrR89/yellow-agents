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
TEXT_BOX_FIRST_ROW = 12  # dialogue / battle text box: rows 12-17 of the 20x18 screen
MAX_ADVANCE_FRAMES = 3000
MAX_WALK_TILES = 20
MAX_CURSOR_MOVES = 10
SETTLE_STABLE_FRAMES = 8  # after choosing: the next screen is drawn once tiles stop changing
SETTLE_MAX_FRAMES = 90


class StopReason(StrEnum):
    MENU = "menu"  # a choice is on screen (cursor ▶)
    OVERWORLD = "overworld"  # the player has control again
    BATTLE_MENU = "battle_menu"  # FIGHT / PKMN / ITEM / RUN
    BLOCKED = "blocked"  # walk: something in the way
    WARPED = "warped"  # walk: the map changed
    TEXT = "text"  # walk: a text box opened
    SCRIPT = "script"  # walk: the game took control; its text comes a few frames later
    BATTLE = "battle"  # walk: a battle started
    DONE = "done"  # walk: all tiles walked
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


# -- pure helpers ---------------------------------------------------------------


def text_ready(tiles: list[int], stable_frames: int) -> bool:
    """A can be pressed: ▼ is in the text box, or the screen stopped changing."""
    return MORE_TEXT in tiles[TEXT_BOX_FIRST_ROW * SCREEN_COLS :] or stable_frames >= STABLE_FRAMES


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
            if text_ready(tiles, stable):
                _note(transcript, screen.lines)
                game.press("a")
                presses += 1
                prev, stable = None, 0
                continue
        elif game.input_enabled() and stable >= STABLE_FRAMES:
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
    """Advance dialogue until a choice, the battle menu or free control. Returns the transcript."""
    action = {"tool": "advance_text"}
    start = game.frame
    screen = game.screen()
    if screen.kind is ScreenKind.OVERWORLD and game.input_enabled():
        return _result(game, action, start, StopReason.OVERWORLD, 0, [])
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
        if (screen.cursor or "").upper() == target:
            break
        moves = cursor_moves(screen, target)
        if not moves:
            raise ActionError(f"cursor is on {screen.cursor!r}, cannot reach {item!r}")
        game.press(moves[0])
        presses += 1
    else:
        raise ActionError(f"cursor did not reach {item!r} in {MAX_CURSOR_MOVES} moves")
    game.press("a")
    presses += 1
    _settle(game)
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
    if not is_battle_menu(state.screen, game.in_battle()):
        raise ActionError("use_move needs the battle menu (FIGHT / PKMN / ITEM / RUN)")
    mon = state.battle.player_mon
    moves = mon.moves if mon else []
    if slot > len(moves):
        raise ActionError(f"no move in slot {slot}; moves: {[m.name for m in moves]}")
    move = moves[slot - 1]
    if move.pp == 0:
        raise ActionError(f"{move.name} has no PP left")
    action = {"tool": "use_move", "slot": slot, "move": move.name}
    start = game.frame
    stop, presses, transcript = _choose(game, "FIGHT")
    if stop is StopReason.MENU:  # the move list
        stop, more, rest = _choose(game, move.name)
        presses += more
        transcript += rest
    return _result(game, action, start, stop, presses, transcript)
