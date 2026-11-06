"""MCP server exposing the emulator, so Claude Code / Claude Desktop / Codex can play.

Configuration (environment variables):
    YELLOW_ROM     path to your own Pokémon Yellow dump (required)
    YELLOW_SYM     default data/generated/pokeyellow.sym
    YELLOW_DATA    default data/generated
    YELLOW_SAVES   default saves/
    YELLOW_RUNS    if set, record every action to <dir>/<run_id>/ (see recorder.py)

Run:  yellow-mcp           (stdio transport)
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .emulator import BUTTONS, Emulator
from .newgame import new_game as _start_new_game
from .newgame import validate_name
from .recorder import RunRecorder

MAX_BUTTONS_PER_CALL = 30
MAX_WAIT_FRAMES = 600
_SAVE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

server = MCPServer(
    name="yellow-agent",
    instructions=(
        "Controls a Pokémon Yellow emulator. Call get_state first: it returns the player's "
        "map, coordinates, party, badges and battle info read from RAM, plus `screen`: "
        "kind ('overworld', 'text' or 'menu'), the visible text lines and the menu item under "
        "the cursor. On 'text' press a to advance; on 'menu' move with up/down and choose with a. "
        "Use screenshot only when that is not enough (e.g. where things are on the map). "
        "Save a state before anything risky. To start over, call new_game with your own name "
        "as player_name (e.g. CLAUDE)."
    ),
)

_emu: Emulator | None = None
_recorder: RunRecorder | None = None
_last_loaded: str | None = None


def emu(*, fresh: bool = False) -> Emulator:
    global _emu
    if fresh and _emu is not None:
        _emu.close()
        _emu = None
    if _emu is None:
        rom = os.environ.get("YELLOW_ROM")
        if not rom or not Path(rom).exists():
            raise ToolError("Set YELLOW_ROM to the path of your own Pokémon Yellow ROM dump.")
        _emu = Emulator(
            rom,
            sym=os.environ.get("YELLOW_SYM", "data/generated/pokeyellow.sym"),
            data_dir=os.environ.get("YELLOW_DATA", "data/generated"),
        )
    return _emu


def _after_action(action: dict) -> dict:
    """State after an action, recorded when YELLOW_RUNS is set. Returned to the client."""
    global _recorder
    e = emu()
    state = e.state()
    runs = os.environ.get("YELLOW_RUNS")
    if runs:
        if _recorder is None:
            _recorder = RunRecorder.start(runs, source="mcp", start_state=_last_loaded)
        _recorder.record(
            frame=e.frame, state=state, action=action, screenshot_png=e.screenshot_png()
        )
    return state.model_dump(mode="json")


def _saves_dir() -> Path:
    return Path(os.environ.get("YELLOW_SAVES", "saves"))


def _save_path(name: str) -> Path:
    # Names come from a model: never let them become arbitrary paths.
    if not _SAVE_NAME.match(name):
        raise ToolError("save name must match [A-Za-z0-9_-]{1,64}")
    return _saves_dir() / f"{name}.state"


@server.tool()
def get_state() -> dict:
    """Game state from RAM: map, x/y, facing, party, badges, money, Pikachu, battle, screen."""
    return emu().state().model_dump(mode="json")


@server.tool()
def press_buttons(buttons: list[str]) -> dict:
    """Press buttons in order (a, b, start, select, up, down, left, right). Returns the new state.

    Outside menus, one directional press walks exactly one tile, or only turns the player when
    the way is blocked; the call returns once the step (and any door/stairs warp) has finished.
    In menus, one directional press moves the cursor one item.
    """
    if not buttons:
        raise ToolError("pass at least one button")
    if len(buttons) > MAX_BUTTONS_PER_CALL:
        raise ToolError(f"at most {MAX_BUTTONS_PER_CALL} buttons per call")
    bad = [b for b in buttons if b not in BUTTONS]
    if bad:
        raise ToolError(f"invalid buttons: {bad}; valid: {list(BUTTONS)}")
    emu().press_sequence(buttons)  # type: ignore[arg-type]
    return _after_action({"tool": "press_buttons", "buttons": buttons})


@server.tool()
def wait(frames: int = 60) -> dict:
    """Let the game run without input (60 frames ≈ 1 second). Returns the new state."""
    frames = max(1, min(frames, MAX_WAIT_FRAMES))
    emu().wait(frames)
    return _after_action({"tool": "wait", "frames": frames})


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
        raise ToolError(f"no save named {name!r}")
    global _last_loaded
    emu().load_state(path)
    _last_loaded = name
    return _after_action({"tool": "load_state", "name": name})


@server.tool()
def new_game(player_name: str, rival_name: str = "GEMINI") -> dict:
    """Power on and start a NEW GAME, typing the names (1-7 letters A-Z). Ends in the bedroom.

    Use your own name as player_name (e.g. CLAUDE). The rival defaults to GEMINI.
    Unsaved progress is lost; a recorded run starts a new recording.
    """
    global _recorder, _last_loaded
    try:
        names = validate_name(player_name), validate_name(rival_name)
    except ValueError as err:
        raise ToolError(str(err)) from None
    if _recorder is not None:
        _recorder.close()
        _recorder = None
    _last_loaded = f"new_game:{names[0]}/{names[1]}"
    _start_new_game(emu(fresh=True), *names)
    return _after_action({"tool": "new_game", "player_name": names[0], "rival_name": names[1]})


@server.tool()
def list_states() -> list[str]:
    """Names of available save states."""
    d = _saves_dir()
    return sorted(p.stem for p in d.glob("*.state")) if d.exists() else []


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
