"""Thin wrapper around PyBoy: headless, fast, deterministic, save-state friendly."""

from __future__ import annotations

import io
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pyboy import PyBoy

from .gamedata import GameData
from .state import SCREEN_COLS, SCREEN_ROWS, GameState, Screen, StateReader
from .symbols import SymbolTable

if TYPE_CHECKING:
    import numpy as np

Button = Literal["a", "b", "start", "select", "up", "down", "left", "right"]
BUTTONS: tuple[str, ...] = ("a", "b", "start", "select", "up", "down", "left", "right")

DIRECTIONS: tuple[str, ...] = ("up", "down", "left", "right")

# Non-directional buttons (A, B, Start, Select): frames held, then frames waited.
HOLD_FRAMES = 8
SETTLE_FRAMES = 16

# Directional buttons are closed-loop (see docs/adr/0001-closed-loop-walking.md): hold until
# wWalkCounter starts counting, release, wait until it reaches 0. Fixed hold/settle timing
# moved 0-2 tiles per press depending on where in the walk cycle the press landed.
STEP_START_FRAMES = 12  # walk starts within 3 frames when possible; longer = blocked/turned
STEP_FRAMES = 40  # a step takes 16-18 frames; this only guards against a hang
WARP_SETTLE_FRAMES = 72  # input works again 64 frames after a stairs warp (measured)


class StepResult(StrEnum):
    MOVED = "moved"
    BLOCKED = "blocked"  # wall, NPC, or input locked: may still have turned to face it
    WARPED = "warped"  # the step changed map (door, stairs, map edge)


class Emulator:
    def __init__(
        self,
        rom: str | Path,
        sym: str | Path = "data/generated/pokeyellow.sym",
        data_dir: str | Path = "data/generated",
        headless: bool = True,
        speed: int = 0,  # 0 = unlimited
    ):
        self.pyboy = PyBoy(str(rom), window="null" if headless else "SDL2", sound_emulated=False)
        self.pyboy.set_emulation_speed(speed)
        self.symbols = SymbolTable.load(sym)
        self.data = GameData.load(data_dir)
        self.reader = StateReader(self._read, self.symbols, self.data)
        # Every action renders its last frame, so screenshots never advance the game: a
        # recorded run (with screenshots) and an unrecorded one stay frame-identical.
        self._rendered = False
        # Called with every emulated frame (160x144 RGBA array) when set, e.g. to record video.
        # Rendering does not change the game: a run with a consumer stays frame-identical.
        self.on_frame: Callable[[np.ndarray], None] | None = None

    @property
    def frame(self) -> int:
        """Frames emulated so far: the deterministic clock for runs and benchmarks."""
        return self.pyboy.frame_count

    # -- memory --------------------------------------------------------------
    def _read(self, address: int, length: int) -> list[int]:
        if length <= 0:  # PyBoy rejects empty slices (e.g. an empty party)
            return []
        return list(self.pyboy.memory[address : address + length])

    def state(self) -> GameState:
        return self.reader.read()

    def tile_map(self) -> list[int]:
        """The 20x18 screen tile buffer (wTileMap)."""
        return self._read(self.symbols.addr("wTileMap"), SCREEN_COLS * SCREEN_ROWS)

    def screen(self) -> Screen:
        """Only the screen part of the state: cheap enough to poll every frame."""
        return self.reader.screen()

    def input_enabled(self) -> bool:
        """False while a script drives the game (wJoyIgnore != 0): presses are ignored."""
        return self._u8("wJoyIgnore") == 0

    def in_battle(self) -> bool:
        return self._u8("wIsInBattle") != 0

    # -- input ---------------------------------------------------------------
    def _u8(self, symbol: str) -> int:
        return self.pyboy.memory[self.symbols.addr(symbol)]

    def press(self, button: Button, hold: int = HOLD_FRAMES, settle: int = SETTLE_FRAMES) -> None:
        if button not in BUTTONS:
            raise ValueError(f"invalid button {button!r}; expected one of {BUTTONS}")
        if button in DIRECTIONS:
            self.step(button)
            return
        self.pyboy.button(button, hold)
        self._tick(hold + settle)

    def step(self, direction: Button) -> StepResult:
        """Walk exactly one tile (or turn / bump) and return once the game accepts input again.

        In menus and text boxes this is just a cursor press: wWalkCounter never starts.
        """
        if direction not in DIRECTIONS:
            raise ValueError(f"invalid direction {direction!r}; expected one of {DIRECTIONS}")
        start_map = self._u8("wCurMap")
        self.pyboy.button_press(direction)
        started = False
        for _ in range(STEP_START_FRAMES):
            self._run(1, render=False)
            if self._u8("wWalkCounter"):
                started = True
                break
        self.pyboy.button_release(direction)
        for _ in range(STEP_FRAMES):
            if self._u8("wWalkCounter") == 0:
                break
            self._run(1, render=False)
        self._tick(1)
        if self._u8("wCurMap") != start_map:
            self._tick(WARP_SETTLE_FRAMES)
            return StepResult.WARPED
        return StepResult.MOVED if started else StepResult.BLOCKED

    def press_sequence(self, buttons: list[Button]) -> None:
        for b in buttons:
            self.press(b)

    def wait(self, frames: int) -> None:
        self._tick(frames)

    def _tick(self, frames: int) -> None:
        """Run frames, rendering only the last one (cheap, and keeps screenshots free)."""
        self._run(frames, render=True)
        self._rendered = True

    def _run(self, frames: int, *, render: bool) -> None:
        if self.on_frame is None:
            self.pyboy.tick(frames, render)
            return
        for _ in range(frames):  # a frame consumer (video) needs every frame drawn
            self.pyboy.tick(1, True)
            self.on_frame(self.pyboy.screen.ndarray)

    # -- screen --------------------------------------------------------------
    def screenshot_png(self) -> bytes:
        if not self._rendered:  # only right after boot: nothing has been drawn yet
            self._tick(1)
        buf = io.BytesIO()
        self.pyboy.screen.image.save(buf, format="PNG")
        return buf.getvalue()

    # -- save states ---------------------------------------------------------
    def save_state(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            self.pyboy.save_state(f)

    def load_state(self, path: str | Path) -> None:
        with open(path, "rb") as f:
            self.pyboy.load_state(f)
        self._tick(1)  # draw the restored screen; always 1 frame, recorded or not

    def close(self) -> None:
        self.pyboy.stop(save=False)
