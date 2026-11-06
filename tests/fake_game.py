"""A scripted stand-in for the emulator: the game is a list of phases.

A phase is one screen. It ends after `frames` frames, or — when `frames` is None — when A is
pressed (a text box waiting for the player). Presses and steps cost frames like the real thing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from yellow_agent.emulator import StepResult
from yellow_agent.state import Battle, BattleKind, GameState, Mon, Move, Screen, ScreenKind
from yellow_agent.text import MORE_TEXT

PRESS_FRAMES = 24  # HOLD_FRAMES + SETTLE_FRAMES
STEP_FRAMES = 17
BLANK = [0x7F] * 360


def text_tiles(arrow: bool) -> list[int]:
    tiles = list(BLANK)
    if arrow:
        tiles[16 * 20 + 18] = MORE_TEXT
    return tiles


@dataclass
class Phase:
    screen: Screen
    tiles: list[int] = field(default_factory=lambda: list(BLANK))
    input_enabled: bool = True
    frames: int | None = None  # None: ends when A is pressed


def text(*lines: str, arrow: bool = True) -> Phase:
    return Phase(Screen(kind=ScreenKind.TEXT, lines=list(lines)), text_tiles(arrow))


def overworld(frames: int | None = None, input_enabled: bool = True) -> Phase:
    return Phase(Screen(kind=ScreenKind.OVERWORLD, lines=[]), frames=frames,
                 input_enabled=input_enabled)  # fmt: skip


def menu(*lines: str, cursor: str) -> Phase:
    return Phase(Screen(kind=ScreenKind.MENU, lines=list(lines), cursor=cursor))


PIKACHU = Mon(
    species="PIKACHU", level=5, hp=19, max_hp=19, status="ok", types=["ELECTRIC"],
    moves=[Move(name="THUNDERSHOCK", pp=30), Move(name="GROWL", pp=0)],
)  # fmt: skip


class FakeGame:
    def __init__(self, phases: list[Phase], *, in_battle: bool = False,
                 steps: list[StepResult] | None = None):  # fmt: skip
        self.phases = phases
        self.i = 0
        self.entered = 0  # frame the current phase started
        self.frame = 0
        self.pressed: list[str] = []
        self._in_battle = in_battle
        self._steps = list(steps or [])

    @property
    def phase(self) -> Phase:
        return self.phases[self.i]

    def _advance(self, frames: int) -> None:
        for _ in range(frames):
            self.frame += 1
            p = self.phase
            if p.frames is not None and self.frame - self.entered >= p.frames:
                self._next()

    def _next(self) -> None:
        if self.i < len(self.phases) - 1:
            self.i += 1
            self.entered = self.frame

    # -- Game protocol --
    def screen(self) -> Screen:
        return self.phase.screen

    def tile_map(self) -> list[int]:
        return self.phase.tiles

    def input_enabled(self) -> bool:
        return self.phase.input_enabled

    def in_battle(self) -> bool:
        return self._in_battle

    def wait(self, frames: int) -> None:
        self._advance(frames)

    def press(self, button: str) -> None:
        self.pressed.append(button)
        p = self.phase
        waiting = p.frames is None and p.screen.kind in (ScreenKind.TEXT, ScreenKind.MENU)
        if button == "a" and waiting:  # A answers a text box or picks the menu item
            self._next()
        self._advance(PRESS_FRAMES)

    def step(self, direction: str) -> StepResult:
        self.pressed.append(direction)
        result = self._steps.pop(0)
        self._advance(STEP_FRAMES)
        return result

    def state(self) -> GameState:
        kind = BattleKind.TRAINER if self._in_battle else BattleKind.NONE
        return GameState(
            player_name="CLAUDE", rival_name="GEMINI", map_id=40, map_name="OAKS_LAB",
            x=5, y=3, facing="up", money=3000, badges=[], pikachu_happiness=90,
            pikachu_mood=128, party=[PIKACHU],
            battle=Battle(kind=kind, player_mon=PIKACHU if self._in_battle else None),
            screen=self.screen(),
        )  # fmt: skip
