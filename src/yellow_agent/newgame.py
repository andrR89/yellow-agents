"""Start a new game from power-on, optionally typing custom player and rival names.

Everything here is closed-loop on RAM: the intro is driven by `screen`, and the naming keyboard
by the position of the ▶ cursor in `wTileMap`. No fixed button sequences.
"""

from __future__ import annotations

import re
from typing import Protocol

from .state import SCREEN_COLS, SCREEN_ROWS, GameState, ScreenKind
from .text import CURSOR

# pret constants/text_constants.asm: PLAYER_NAME_LENGTH EQU 8 (7 letters + terminator)
MAX_NAME_LETTERS = 7
# Letters we type. Upper case only: pret data/text/alphabets.asm, UpperCaseAlphabet rows 1-3.
KEYBOARD_ROWS = ("ABCDEFGHI", "JKLMNOPQR", "STUVWXYZ")
# Tile-map cell of the ▶ when "A" is selected, and the spacing between letters and rows
# (a blank tile in between; the ▶ sits just left of its letter). Measured on the real screen.
KEYBOARD_FIRST_ROW, KEYBOARD_FIRST_COL, KEYBOARD_STEP = 5, 1, 2
_NAME = re.compile(rf"^[A-Z]{{1,{MAX_NAME_LETTERS}}}$")
_MAX_INTRO_ACTIONS = 400
_MAX_MOVES_PER_LETTER = 20


class _Emu(Protocol):
    def state(self) -> GameState: ...
    def press(self, button: str) -> None: ...
    def wait(self, frames: int) -> None: ...
    def tile_map(self) -> list[int]: ...


def validate_name(name: str) -> str:
    if not _NAME.match(name):
        raise ValueError(f"name must be 1-{MAX_NAME_LETTERS} letters A-Z, got {name!r}")
    return name


def keyboard_position(letter: str) -> tuple[int, int]:
    """(row, col) in the 20x18 tile map where the ▶ cursor sits when `letter` is selected."""
    for j, row in enumerate(KEYBOARD_ROWS):
        if letter in row:
            return (
                KEYBOARD_FIRST_ROW + KEYBOARD_STEP * j,
                KEYBOARD_FIRST_COL + KEYBOARD_STEP * row.index(letter),
            )
    raise ValueError(f"{letter!r} is not on the keyboard")


def cursor_position(tiles: list[int]) -> tuple[int, int] | None:
    """(row, col) of the ▶ cursor in a 20x18 tile map, or None."""
    try:
        index = tiles[: SCREEN_COLS * SCREEN_ROWS].index(CURSOR)
    except ValueError:
        return None
    return divmod(index, SCREEN_COLS)


def _type_name(emu: _Emu, name: str) -> None:
    for letter in name:
        target = keyboard_position(letter)
        for _ in range(_MAX_MOVES_PER_LETTER):
            pos = cursor_position(emu.tile_map())
            if pos is None:
                raise RuntimeError("naming screen cursor not found")
            if pos == target:
                break
            (r, c), (tr, tc) = pos, target
            emu.press("down" if r < tr else "up" if r > tr else "right" if c < tc else "left")
        else:
            raise RuntimeError(f"could not reach {letter!r} on the naming keyboard")
        emu.press("a")
    emu.press("start")  # submit the name


def new_game(emu: _Emu, player_name: str | None = None, rival_name: str | None = None) -> None:
    """Power-on -> bedroom with free control. None keeps the first preset name (YELLOW / BLUE)."""
    names = [validate_name(n) if n is not None else None for n in (player_name, rival_name)]
    asked = 0  # name menus seen so far: player first, then rival
    for _ in range(_MAX_INTRO_ACTIONS):
        s = emu.state()
        if s.map_name == "REDS_HOUSE_2F" and s.screen.kind is ScreenKind.OVERWORLD:
            emu.wait(60)  # let the fade-in finish
            if emu.state().screen.kind is ScreenKind.OVERWORLD:
                return
        if s.screen.kind is ScreenKind.MENU:
            if s.screen.cursor == "NEW NAME":
                name = names[asked] if asked < len(names) else None
                asked += 1
                if name is None:
                    emu.press("down")  # first preset name
                    emu.press("a")
                else:
                    emu.press("a")  # open the keyboard
                    emu.wait(30)
                    _type_name(emu, name)
            else:
                emu.press("a")
        elif s.screen.kind is ScreenKind.TEXT:
            emu.press("a")
        elif s.screen.kind is ScreenKind.CUTSCENE:
            emu.press("start")  # skip the intro / leave the title screen
        else:
            emu.wait(10)
    raise RuntimeError("new game did not reach the bedroom")
