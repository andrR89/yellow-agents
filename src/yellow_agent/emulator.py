"""Thin wrapper around PyBoy: headless, fast, deterministic, save-state friendly."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Literal

from pyboy import PyBoy

from .gamedata import GameData
from .state import GameState, StateReader
from .symbols import SymbolTable

Button = Literal["a", "b", "start", "select", "up", "down", "left", "right"]
BUTTONS: tuple[str, ...] = ("a", "b", "start", "select", "up", "down", "left", "right")

# Frames a single press is held, and frames waited afterwards so the game reacts.
# Walking one tile takes ~16 frames; tune these with the eval scenarios.
HOLD_FRAMES = 8
SETTLE_FRAMES = 16


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
        self.reader = StateReader(self._read, self.symbols, GameData.load(data_dir))

    # -- memory --------------------------------------------------------------
    def _read(self, address: int, length: int) -> list[int]:
        return list(self.pyboy.memory[address : address + length])

    def state(self) -> GameState:
        return self.reader.read()

    # -- input ---------------------------------------------------------------
    def press(self, button: Button, hold: int = HOLD_FRAMES, settle: int = SETTLE_FRAMES) -> None:
        if button not in BUTTONS:
            raise ValueError(f"invalid button {button!r}; expected one of {BUTTONS}")
        self.pyboy.button(button, hold)
        self.pyboy.tick(hold + settle, False)

    def press_sequence(self, buttons: list[Button]) -> None:
        for b in buttons:
            self.press(b)

    def wait(self, frames: int) -> None:
        self.pyboy.tick(frames, False)

    # -- screen --------------------------------------------------------------
    def screenshot_png(self) -> bytes:
        self.pyboy.tick(1, True)  # render the current frame
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

    def close(self) -> None:
        self.pyboy.stop(save=False)
