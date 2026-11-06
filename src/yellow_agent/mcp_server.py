"""MCP server exposing the emulator, so Claude Code / Claude Desktop / Codex can play.

Configuration (environment variables):
    YELLOW_ROM     path to your own Pokémon Yellow dump (required)
    YELLOW_SYM     default data/generated/pokeyellow.sym
    YELLOW_DATA    default data/generated
    YELLOW_SAVES   default saves/

Run:  yellow-mcp           (stdio transport)
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from mcp.server.mcpserver import Image, MCPServer

from .emulator import BUTTONS, Emulator

MAX_BUTTONS_PER_CALL = 30
MAX_WAIT_FRAMES = 600
_SAVE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

server = MCPServer(
    name="yellow-agent",
    instructions=(
        "Controls a Pokémon Yellow emulator. Call get_state first: it returns the player's "
        "map, coordinates, party, badges and battle info read from RAM. Use press_buttons to act "
        "and screenshot only when the RAM state is not enough (menus, dialogue). "
        "Save a state before anything risky."
    ),
)

_emu: Emulator | None = None


def emu() -> Emulator:
    global _emu
    if _emu is None:
        rom = os.environ.get("YELLOW_ROM")
        if not rom or not Path(rom).exists():
            raise RuntimeError("Set YELLOW_ROM to the path of your own Pokémon Yellow ROM dump.")
        _emu = Emulator(
            rom,
            sym=os.environ.get("YELLOW_SYM", "data/generated/pokeyellow.sym"),
            data_dir=os.environ.get("YELLOW_DATA", "data/generated"),
        )
    return _emu


def _saves_dir() -> Path:
    return Path(os.environ.get("YELLOW_SAVES", "saves"))


def _save_path(name: str) -> Path:
    # Names come from a model: never let them become arbitrary paths.
    if not _SAVE_NAME.match(name):
        raise ValueError("save name must match [A-Za-z0-9_-]{1,64}")
    return _saves_dir() / f"{name}.state"


@server.tool()
def get_state() -> dict:
    """Current game state from RAM: map, x/y, facing, party, badges, money, Pikachu, battle."""
    return emu().state().model_dump(mode="json")


@server.tool()
def press_buttons(buttons: list[str]) -> dict:
    """Press buttons in order (a, b, start, select, up, down, left, right). Returns the new state.

    One directional press moves one tile (or turns to face that way first).
    """
    if not buttons:
        raise ValueError("pass at least one button")
    if len(buttons) > MAX_BUTTONS_PER_CALL:
        raise ValueError(f"at most {MAX_BUTTONS_PER_CALL} buttons per call")
    bad = [b for b in buttons if b not in BUTTONS]
    if bad:
        raise ValueError(f"invalid buttons: {bad}; valid: {list(BUTTONS)}")
    e = emu()
    e.press_sequence(buttons)  # type: ignore[arg-type]
    return e.state().model_dump(mode="json")


@server.tool()
def wait(frames: int = 60) -> dict:
    """Let the game run without input (60 frames ≈ 1 second). Returns the new state."""
    e = emu()
    e.wait(max(1, min(frames, MAX_WAIT_FRAMES)))
    return e.state().model_dump(mode="json")


@server.tool()
def screenshot() -> Image:
    """PNG of the current screen (160x144). Use for menus and dialogue."""
    return Image(data=emu().screenshot_png(), format="png")


@server.tool()
def save_state(name: str) -> str:
    """Save the full emulator state under a name (letters, digits, - and _)."""
    path = _save_path(name)
    emu().save_state(path)
    return f"saved {path.name}"


@server.tool()
def load_state(name: str) -> dict:
    """Restore a saved state by name. Returns the restored game state."""
    path = _save_path(name)
    if not path.exists():
        raise FileNotFoundError(f"no save named {name!r}")
    e = emu()
    e.load_state(path)
    return e.state().model_dump(mode="json")


@server.tool()
def list_states() -> list[str]:
    """Names of available save states."""
    d = _saves_dir()
    return sorted(p.stem for p in d.glob("*.state")) if d.exists() else []


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
