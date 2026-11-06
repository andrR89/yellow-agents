"""The agent loop: state -> model -> one action -> state, recorded step by step.

One turn = one model call = one tool call. The prompt is rebuilt every turn from the RAM state,
the goal and the last few actions with their results, so any model (with or without long
context) sees the same thing, and the cost per turn stays flat.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from . import actions
from .actions import ActionError, ActionResult
from .models.base import ChatModel, Message, ModelResponse, ToolCall, ToolSpec
from .state import GameState

if TYPE_CHECKING:
    from .recorder import RunRecorder
    from .scenarios import Judge

HISTORY_TURNS = 8
LOOP_TURNS = 3  # the same action and outcome this many times in a row -> a warning in the prompt
TRANSCRIPT_LINES = 6
MAX_MODEL_ERRORS = 3  # consecutive failed model calls before the run is abandoned
MAX_OUTPUT_TOKENS = 400

SYSTEM = """You are playing Pokémon Yellow on a Game Boy emulator, through tools.
Every turn you get the goal, the game state read from the game's memory, and your recent
actions with what happened. Call exactly one tool per turn.

- screen 'text': call advance_text. It reads the whole dialogue and stops at the next choice.
- screen 'menu': call choose with an item that is on screen (e.g. YES, NO, FIGHT).
- screen 'overworld': go_to(x, y) walks the shortest way to a cell of this map (it goes around
  walls and people, and walks out through a door on the map's edge). MAP lists the exits (doors,
  stairs, and the map edges that lead to other maps) and the people around. walk(direction,
  tiles) takes single steps; talk() talks to whatever you are facing.
  Coordinates: x grows to the right, y grows downward, so 'up' decreases y.
  A walk or go_to stops early with 'blocked', 'warped' (you went through a door or stairs),
  'text' or 'script' (the game took over: call advance_text); go_to says 'no_path' when the cell
  can't be reached. To leave a map by its edge, go_to a cell on that edge, then walk off it.
- In a battle at FIGHT / PKMN / ITEM / RUN: use_move(slot) picks a move and plays the turn.
- press_buttons and wait are fallbacks for anything else.
Fill each tool's `reason` with one short sentence: what you are doing and why."""

_DIRECTION = {"type": "string", "enum": list(actions.DIRECTIONS)}
TOOLS: list[ToolSpec] = [
    ToolSpec("advance_text", "Advance dialogue until a choice, the battle menu or free control.",
             {"type": "object", "properties": {}}),
    ToolSpec("walk", "Walk up to `tiles` tiles in one direction; stops early if interrupted.",
             {"type": "object", "properties": {
                 "direction": _DIRECTION,
                 "tiles": {"type": "integer", "minimum": 1, "maximum": actions.MAX_WALK_TILES}},
              "required": ["direction", "tiles"]}),
    ToolSpec("go_to", "Walk the shortest way to cell (x, y) of the current map.",
             {"type": "object", "properties": {
                 "x": {"type": "integer", "minimum": 0}, "y": {"type": "integer", "minimum": 0}},
              "required": ["x", "y"]}),
    ToolSpec("talk", "Interact with whatever the player is facing (person, sign, item).",
             {"type": "object", "properties": {}}),
    ToolSpec("choose", "Pick a menu item by its name as shown on screen.",
             {"type": "object", "properties": {"item": {"type": "string"}},
              "required": ["item"]}),
    ToolSpec("use_move", "In battle at FIGHT/PKMN/ITEM/RUN: use the move in slot 1-4.",
             {"type": "object", "properties": {
                 "slot": {"type": "integer", "minimum": 1, "maximum": 4}},
              "required": ["slot"]}),
    ToolSpec("press_buttons", "Press Game Boy buttons in order (fallback).",
             {"type": "object", "properties": {"buttons": {
                 "type": "array", "maxItems": actions.MAX_BUTTONS,
                 "items": {"type": "string", "enum": list(actions.BUTTONS)}}},
              "required": ["buttons"]}),
    ToolSpec("wait", "Let the game run without input (60 frames = 1 second).",
             {"type": "object", "properties": {
                 "frames": {"type": "integer", "minimum": 1, "maximum": actions.MAX_WAIT_FRAMES}},
              "required": ["frames"]}),
]  # fmt: skip
_REASON = {"type": "string", "description": "One short sentence: what you are doing and why."}
for _tool in TOOLS:  # every tool takes an optional `reason`: the replay shows it
    _tool.parameters.setdefault("properties", {})["reason"] = _REASON


# -- what the model sees ----------------------------------------------------------------


def _mon(m: Any) -> dict[str, Any]:
    return {
        "species": m.species,
        "level": m.level,
        "hp": f"{m.hp}/{m.max_hp}",
        "status": m.status,
        "moves": [f"{mv.name} ({mv.pp} PP)" for mv in m.moves],
    }


def observe(state: GameState) -> dict[str, Any]:
    """The state, trimmed to what a decision needs."""
    obs: dict[str, Any] = {
        "map": state.map_name,
        "x": state.x,
        "y": state.y,
        "facing": state.facing,
        "screen": {"kind": state.screen.kind.value, "lines": state.screen.lines},
        "party": [_mon(m) for m in state.party],
    }
    if state.screen.cursor:
        obs["screen"]["cursor"] = state.screen.cursor
    b = state.battle
    if b.kind.value != "none":
        obs["battle"] = {"kind": b.kind.value}
        if b.player_mon:
            obs["battle"]["you"] = _mon(b.player_mon)
        if b.enemy_mon:
            obs["battle"]["enemy"] = {
                "species": b.enemy_mon.species,
                "level": b.enemy_mon.level,
                "hp": f"{b.enemy_mon.hp}/{b.enemy_mon.max_hp}",
            }
    return obs


@dataclass
class HistoryItem:
    turn: int
    action: dict[str, Any]
    outcome: str


def describe(result: ActionResult) -> str:
    parts = [f"stop={result.stop.value}"]
    if result.tiles is not None:
        parts.append(f"tiles={result.tiles}")
    s = result.state
    parts.append(f"now at {s.map_name} ({s.x},{s.y})")
    if result.transcript:
        said = " / ".join(result.transcript[-TRANSCRIPT_LINES:])
        parts.append(f'text: "{said}"')
    return ", ".join(parts)


def observe_map(grid: Any) -> dict[str, Any]:
    """Size, exits and people of the current map (navigation.MapGrid)."""
    exits = []
    for e in grid.exits:
        if e.kind == "warp":
            exits.append({"to": e.to, "x": e.x, "y": e.y})
        else:
            exits.append({"to": e.to, "edge": e.side})
    return {
        "size": {"width": grid.width, "height": grid.height},
        "exits": exits,
        "people": [{"who": p.who, "x": p.x, "y": p.y} for p in grid.people],
    }


def loop_warning(history: list[HistoryItem]) -> str | None:
    """The same action with the same outcome LOOP_TURNS times in a row: say so, loudly."""
    last = history[-LOOP_TURNS:]
    if len(last) < LOOP_TURNS:
        return None
    first = (json.dumps(last[0].action, sort_keys=True), last[0].outcome)
    if all((json.dumps(h.action, sort_keys=True), h.outcome) == first for h in last):
        return (f"WARNING: your last {LOOP_TURNS} actions were the same and got the same result. "
                "Doing it again will not work: do something different (another direction, go_to "
                "an exit from MAP, or advance_text if the game is busy).")  # fmt: skip
    return None


def build_prompt(goal: str, turn: int, max_turns: int, state: GameState,
                 history: list[HistoryItem], grid: Any = None) -> str:  # fmt: skip
    lines = [f"GOAL: {goal}", f"TURN {turn} of {max_turns}", ""]
    lines.append("STATE: " + json.dumps(observe(state), ensure_ascii=False))
    if grid is not None:
        lines.append("MAP: " + json.dumps(observe_map(grid), ensure_ascii=False))
    lines.append("")
    if history:
        lines.append("RECENT ACTIONS (oldest first):")
        for h in history[-HISTORY_TURNS:]:
            lines.append(f"{h.turn}. {json.dumps(h.action, ensure_ascii=False)} -> {h.outcome}")
    else:
        lines.append("RECENT ACTIONS: none yet.")
    lines.append("")
    if warning := loop_warning(history):
        lines.append(warning)
        lines.append("")
    lines.append("Call exactly one tool.")
    return "\n".join(lines)


# -- tool call -> action ----------------------------------------------------------------


def _int(args: dict[str, Any], key: str) -> int:
    try:
        return int(args[key])
    except KeyError:
        raise ActionError(f"missing argument {key!r}") from None
    except (TypeError, ValueError):
        raise ActionError(f"{key!r} must be an integer") from None


def _str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ActionError(f"missing argument {key!r}")
    return value


def execute(game: actions.Game, call: ToolCall) -> ActionResult:
    """Run one tool call. Raises ActionError for anything invalid (nothing pressed then)."""
    a = {k: v for k, v in call.arguments.items() if k != "reason"}
    if "_raw" in a:
        raise ActionError(f"arguments are not valid JSON: {a['_raw']!r}")
    match call.name:
        case "advance_text":
            return actions.advance_text(game)
        case "walk":
            return actions.walk(game, _str(a, "direction"), _int(a, "tiles"))
        case "go_to":
            return actions.go_to(game, a.get("x"), a.get("y"))
        case "talk":
            return actions.talk(game)
        case "choose":
            return actions.choose(game, _str(a, "item"))
        case "use_move":
            return actions.use_move(game, _int(a, "slot"))
        case "press_buttons":
            buttons = a.get("buttons")
            if not isinstance(buttons, list):
                raise ActionError("buttons must be a list")
            return actions.press_buttons(game, [str(b) for b in buttons])
        case "wait":
            return actions.wait(game, _int(a, "frames"))
    raise ActionError(f"unknown tool {call.name!r}; tools: {[t.name for t in TOOLS]}")


# -- the loop -------------------------------------------------------------------------------

Stop = Literal["success", "failure", "max_turns", "budget", "model_error"]


@dataclass
class AgentRun:
    stop: Stop = "max_turns"
    turns: int = 0
    frames: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    model_latency_s: float = 0.0
    invalid_actions: int = 0  # tool calls rejected (bad tool, args, wrong screen)
    no_tool_calls: int = 0  # answers without a tool call
    model_errors: int = 0
    last_error: str | None = None  # the last failed model call, for the report
    tools: dict[str, int] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.stop == "success"


def _response_json(resp: ModelResponse) -> str:
    calls = [{"name": c.name, "arguments": c.arguments} for c in resp.tool_calls]
    return json.dumps({"text": resp.text, "tool_calls": calls}, ensure_ascii=False)


def run_agent(
    game: Any,  # Emulator (actions.Game + frame, state(), screenshot_png())
    model: ChatModel,
    goal: str,
    judge: Judge,
    *,
    max_turns: int,
    budget_usd: float,
    recorder: RunRecorder | None = None,
) -> AgentRun:
    run = AgentRun()
    start_frame = game.frame
    history: list[HistoryItem] = []
    errors_in_a_row = 0
    for turn in range(1, max_turns + 1):
        state = game.state()
        # MAP only when walking around: in text, menus and battles it distracted small models
        # (llama3.1:8b called go_to 8 times from the move list, session 8).
        walking = state.screen.kind.value == "overworld" and state.battle.kind.value == "none"
        grid = game.map_grid() if walking and hasattr(game, "map_grid") else None
        prompt = build_prompt(goal, turn, max_turns, state, history, grid)
        try:
            resp = model.complete(SYSTEM, [Message("user", prompt)], TOOLS, MAX_OUTPUT_TOKENS)
        except Exception as err:  # network, rate limit, provider error: count and retry
            run.model_errors += 1
            run.last_error = f"{type(err).__name__}: {err}"[:300]
            errors_in_a_row += 1
            history.append(HistoryItem(turn, {"tool": "none"}, f"model call failed: {err}"))
            if errors_in_a_row >= MAX_MODEL_ERRORS:
                run.stop = "model_error"
                break
            time.sleep(2 * errors_in_a_row)
            continue
        errors_in_a_row = 0
        run.turns = turn
        run.cost_usd += resp.cost_usd
        run.input_tokens += resp.usage.input_tokens
        run.output_tokens += resp.usage.output_tokens
        run.model_latency_s += resp.latency_s

        result: ActionResult | None = None
        if not resp.tool_calls:
            run.no_tool_calls += 1
            action: dict[str, Any] = {"tool": "none"}
            outcome = "ERROR: no tool was called. Call exactly one tool."
        else:
            call = resp.tool_calls[0]
            reason = call.arguments.get("reason")
            if isinstance(reason, str) and reason.strip() and not resp.text:
                resp.text = reason.strip()  # what the model "said" for this turn
            action = {
                "tool": call.name,
                **{k: v for k, v in call.arguments.items() if k != "reason"},
            }
            run.tools[call.name] = run.tools.get(call.name, 0) + 1
            try:
                result = execute(game, call)
                action = result.action
                outcome = describe(result)
            except ActionError as err:
                run.invalid_actions += 1
                outcome = f"ERROR: {err}"
        history.append(HistoryItem(turn, action, outcome))

        if recorder is not None:
            after = result.state if result else game.state()
            extra = result.extra() if result else {"error": outcome}
            recorder.record(
                frame=game.frame,
                state=after,
                action=action,
                screenshot_png=game.screenshot_png(),
                model=model.name,
                prompt=prompt,
                response=_response_json(resp),
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
                latency_ms=round(resp.latency_s * 1000, 1),
                cost_usd=resp.cost_usd,
                extra=extra,
            )

        verdict = judge(game)
        if verdict is not None:
            run.stop = verdict
            break
        if run.cost_usd >= budget_usd:
            run.stop = "budget"
            break
    run.frames = game.frame - start_frame
    return run
