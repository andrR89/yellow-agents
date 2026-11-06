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

from . import actions
from .actions import ActionError, ActionResult
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
        "the cursor. Prefer the high-level tools: advance_text on 'text' (it reads the whole "
        "dialogue and stops at the next choice), choose(item) on 'menu', walk(direction, "
        "tiles) and talk() on 'overworld', use_move(slot) in battle. Each returns `stop`, "
        "which says why it stopped. press_buttons and wait are there for anything else. "
        "Use screenshot only when the state is not enough (e.g. where things are on the "
        "map). Save a state before anything risky. To start over, call new_game with your "
        "own name as player_name (e.g. CLAUDE)."
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


def _record(state, action: dict, extra: dict | None = None) -> None:
    """Record one step when YELLOW_RUNS is set."""
    global _recorder
    runs = os.environ.get("YELLOW_RUNS")
    if not runs:
        return
    e = emu()
    if _recorder is None:
        _recorder = RunRecorder.start(runs, source="mcp", start_state=_last_loaded)
    _recorder.record(
        frame=e.frame,
        state=state,
        action=action,
        screenshot_png=e.screenshot_png(),
        extra=extra or {},
    )


def _after_action(action: dict) -> dict:
    """State after a raw action (buttons, wait, load), recorded. Returned to the client."""
    state = emu().state()
    _record(state, action)
    return state.model_dump(mode="json")


def _run_action(fn, *args) -> dict:
    """Run a high-level action; its ActionResult is recorded and returned."""
    try:
        result: ActionResult = fn(emu(), *args)
    except ActionError as err:
        raise ToolError(str(err)) from None
    _record(result.state, result.action, result.extra())
    return result.model_dump(mode="json")


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
def advance_text() -> dict:
    """Advance dialogue: presses A each time a text box is ready, through scripted scenes,
    until a choice (menu), the battle menu or free control. Returns `stop` (why it stopped),
    `transcript` (everything said) and the state."""
    return _run_action(actions.advance_text)


@server.tool()
def walk(direction: str, tiles: int = 1) -> dict:
    """Walk up to `tiles` (1-20) tiles. Stops early when blocked, at a door/warp, when a text box
    opens, when the game takes control (`script`: call advance_text) or a battle starts."""
    try:
        actions.validate_walk(direction, tiles)
    except ActionError as err:
        raise ToolError(str(err)) from None
    return _run_action(actions.walk, direction, tiles)


@server.tool()
def talk() -> dict:
    """Interact with what the player faces (person, sign, item) and read what it says."""
    return _run_action(actions.talk)


@server.tool()
def choose(item: str) -> dict:
    """Pick a menu item by its name as shown on screen (e.g. YES, NO, FIGHT, a move)."""
    if not item.strip():
        raise ToolError("item must be the name of a menu item on screen")
    return _run_action(actions.choose, item)


@server.tool()
def use_move(slot: int) -> dict:
    """In battle, at FIGHT/PKMN/ITEM/RUN: use the move in `slot` (1-4) and play out the turn."""
    try:
        actions.validate_slot(slot)
    except ActionError as err:
        raise ToolError(str(err)) from None
    return _run_action(actions.use_move, slot)


@server.tool()
def wait(frames: int = 60) -> dict:
    """Let the game run without input (60 frames ≈ 1 s; at most 600 per call). Returns the state."""
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
