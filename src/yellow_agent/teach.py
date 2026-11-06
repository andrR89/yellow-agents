"""Lessons for the local model: (prompt, right tool call) pairs from a scripted expert.

The expert plays the training scenarios with the same tools and sees the same prompt the agent
loop builds (goal, trimmed state, last actions). To show the model more than one path, the
expert sometimes takes a random detour of 1-3 tiles; the detour itself is NOT a lesson, but
walking back from it is (the prompt shows the detour in RECENT ACTIONS). No API calls, no cost.

Held out on purpose: `route1` is never used here, so the benchmark can tell learning the game
from memorising the lessons.

CLI::

    yellow-teach --episodes 60 --out data/generated/teach    # train.jsonl + stats.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .actions import ActionError, StopReason, is_battle_menu
from .agent import SYSTEM, TOOLS, HistoryItem, build_prompt, describe, execute
from .baseline import HOUSE_TO_NORTH_EXIT, LAB_TO_OAK
from .models.base import ToolCall
from .newgame import new_game
from .scenarios import RIVAL, SCENARIOS
from .state import GameState, ScreenKind

if TYPE_CHECKING:
    from .emulator import Emulator

TRAIN_SCENARIOS = ("pikachu", "rival_battle")  # route1 stays out: the held-out test
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}
DELTA = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
PLAYER_NAMES = ("CLAUDE", "QWEN", "GPT", "ASH", "RED", "YELLOW", "AGENT")


@dataclass
class Path_:
    """Tiles of the known-good route on one map, in walking order, and what to do at its end."""

    tiles: list[tuple[int, int]] = field(default_factory=list)
    end_dir: str | None = None  # last step from the final tile (a warp, the grass, a turn)


def record_paths(emu: Emulator) -> dict[str, Path_]:
    """Walk the baseline route once (new game -> grass -> lab) and keep each map's tiles."""
    paths: dict[str, Path_] = {}
    new_game(emu, "CLAUDE", RIVAL)
    s = emu.state()
    paths.setdefault(s.map_name, Path_()).tiles.append((s.x, s.y))
    for direction in [*HOUSE_TO_NORTH_EXIT, "up"]:  # the last "up" steps into the grass
        before = emu.state()
        emu.step(direction)
        after = emu.state()
        if after.map_name != before.map_name or (after.x, after.y) == (before.x, before.y):
            paths[before.map_name].end_dir = direction  # warp, grass trigger or a wall
            if after.map_name != before.map_name:
                paths.setdefault(after.map_name, Path_()).tiles.append((after.x, after.y))
            continue
        paths.setdefault(after.map_name, Path_()).tiles.append((after.x, after.y))
    # Oak's lab: from (5,3) to below the ball, then face up (and talk).
    lab = Path_(tiles=[(5, 3)], end_dir="up")
    x, y = 5, 3
    for direction in LAB_TO_OAK[:-1]:
        dx, dy = DELTA[direction]
        x, y = x + dx, y + dy
        lab.tiles.append((x, y))
    paths["OAKS_LAB:ball"] = lab
    # With Pikachu: walk south until GEMINI stops you.
    paths["OAKS_LAB:rival"] = Path_(tiles=[(5, y) for y in range(3, 7)], end_dir="down")
    for p in paths.values():  # collapse turns-in-place recorded as repeats
        p.tiles = [t for i, t in enumerate(p.tiles) if i == 0 or t != p.tiles[i - 1]]
    return paths


def _path_key(state: GameState) -> str:
    if state.map_name == "OAKS_LAB":
        has_pikachu = any(m.species == "PIKACHU" for m in state.party)
        return "OAKS_LAB:rival" if has_pikachu else "OAKS_LAB:ball"
    return state.map_name


def expert_call(state: GameState, in_battle: bool, paths: dict[str, Path_]) -> ToolCall:
    """The right tool call for this state, on the training scenarios."""
    screen = state.screen
    if screen.kind is ScreenKind.TEXT:
        return ToolCall("advance_text", {"reason": "Read the dialogue to the next choice."})
    if screen.kind is ScreenKind.MENU:
        if any("nickname" in line for line in screen.lines):
            return ToolCall(
                "choose", {"item": "NO", "reason": "The goal says to decline a nickname."}
            )
        if is_battle_menu(screen, in_battle) and state.battle.kind.value == "trainer":
            return ToolCall("use_move", {"slot": 1, "reason": "Attack with THUNDERSHOCK."})
        item = screen.cursor or "YES"  # Oak's catch demo: accept what the game picked
        return ToolCall("choose", {"item": item, "reason": "Confirm the highlighted choice."})
    path = paths.get(_path_key(state))
    if path is None:
        return ToolCall("advance_text", {"reason": "Wait for the scene to go on."})
    here = (state.x, state.y)
    if here == path.tiles[-1]:
        if path.end_dir is None:
            return ToolCall("advance_text", {"reason": "Wait for the scene to go on."})
        if _path_key(state) == "OAKS_LAB:ball" and state.facing == "up":
            return ToolCall("talk", {"reason": "Take the Poké Ball on the table above me."})
        return ToolCall("walk", {"direction": path.end_dir, "tiles": 1,
                                 "reason": "One more step, as the goal describes."})  # fmt: skip
    if here in path.tiles:
        i = path.tiles.index(here)
        nxt = path.tiles[i + 1]
        direction = _direction(here, nxt)
        n = 1
        while (
            i + n + 1 < len(path.tiles)
            and _direction(path.tiles[i + n], path.tiles[i + n + 1]) == direction
        ):
            n += 1
        return ToolCall("walk", {"direction": direction, "tiles": n,
                                 "reason": "Follow the way the goal describes."})  # fmt: skip
    # Off the route without a known detour: head for the nearest route tile.
    target = min(path.tiles, key=lambda t: abs(t[0] - here[0]) + abs(t[1] - here[1]))
    dx, dy = target[0] - here[0], target[1] - here[1]
    direction = ("right" if dx > 0 else "left") if dx else ("down" if dy > 0 else "up")
    return ToolCall("walk", {"direction": direction, "tiles": max(abs(dx), abs(dy)) or 1,
                             "reason": "Get back on the way the goal describes."})  # fmt: skip


def _direction(a: tuple[int, int], b: tuple[int, int]) -> str:
    dx, dy = b[0] - a[0], b[1] - a[1]
    for name, (ddx, ddy) in DELTA.items():
        if (dx, dy) == (ddx, ddy):
            return name
    raise ValueError(f"route tiles not adjacent: {a} -> {b}")


def lesson(prompt: str, call: ToolCall) -> dict[str, Any]:
    """One training row in chat format (the tools list is added by the trainer)."""
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": "",
             "tool_calls": [{"type": "function",
                             "function": {"name": call.name, "arguments": call.arguments}}]},
        ]
    }  # fmt: skip


def episode(emu: Emulator, scenario_name: str, paths: dict[str, Path_], rng: random.Random,
            detour_p: float) -> Iterator[dict[str, Any]]:  # fmt: skip
    scenario = SCENARIOS[scenario_name]
    scenario.setup(emu, rng.choice(PLAYER_NAMES))
    judge = scenario.judge()
    history: list[HistoryItem] = []
    pending_undo: tuple[str, int] | None = None
    for turn in range(1, scenario.max_turns + 1):
        state = emu.state()
        prompt = build_prompt(scenario.goal, turn, scenario.max_turns, state, history)
        detour = (
            pending_undo is None
            and state.screen.kind is ScreenKind.OVERWORLD
            and emu.input_enabled()
            and rng.random() < detour_p
        )
        if pending_undo is not None:
            direction, tiles = pending_undo
            undo = "Undo my detour and get back on the way."
            call = ToolCall("walk", {"direction": direction, "tiles": tiles, "reason": undo})
            pending_undo = None
        elif detour:
            call = ToolCall(
                "walk", {"direction": rng.choice(list(DELTA)), "tiles": rng.randint(1, 3)}
            )
        else:
            call = expert_call(state, emu.in_battle(), paths)
        if not detour:
            yield lesson(prompt, call)
        try:
            result = execute(emu, call)
        except ActionError as err:
            history.append(
                HistoryItem(turn, {"tool": call.name, **call.arguments}, f"ERROR: {err}")
            )
            continue
        action = result.action
        history.append(HistoryItem(turn, action, describe(result)))
        if detour:
            if result.stop not in (StopReason.DONE, StopReason.BLOCKED):
                return  # went through a door or started a scene: the expert can't undo that
            if result.tiles:
                pending_undo = (OPPOSITE[call.arguments["direction"]], result.tiles)
        if judge(emu) is not None:
            return


def main() -> None:
    from .emulator import Emulator

    parser = argparse.ArgumentParser(description="Generate lessons for the local model.")
    parser.add_argument("--episodes", type=int, default=60, help="per training scenario")
    parser.add_argument("--detour", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=Path("data/generated/teach"))
    args = parser.parse_args()
    rom = os.environ.get("YELLOW_ROM")
    if not rom or not Path(rom).is_file():
        parser.error("set YELLOW_ROM to your own Pokémon Yellow dump")

    def emulator() -> Emulator:
        return Emulator(rom, sym=os.environ.get("YELLOW_SYM", "data/generated/pokeyellow.sym"),
                        data_dir=os.environ.get("YELLOW_DATA", "data/generated"))  # fmt: skip

    emu = emulator()
    paths = record_paths(emu)
    emu.close()
    rng = random.Random(args.seed)
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    tools: Counter[str] = Counter()
    per_scenario: Counter[str] = Counter()
    for scenario in TRAIN_SCENARIOS:
        for i in range(args.episodes):
            emu = emulator()
            try:
                for row in episode(emu, scenario, paths, rng, args.detour if i else 0.0):
                    key = json.dumps(row, sort_keys=True)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(row)
                    tools[row["messages"][2]["tool_calls"][0]["function"]["name"]] += 1
                    per_scenario[scenario] += 1
            finally:
                emu.close()
            print(f"{scenario} episode {i + 1}/{args.episodes}: {len(rows)} lessons", flush=True)
    rng.shuffle(rows)
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "train.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tool_schemas = [
        {"type": "function", "function": {"name": t.name, "description": t.description,
                                          "parameters": t.parameters}}
        for t in TOOLS
    ]  # fmt: skip
    (args.out / "tools.json").write_text(json.dumps(tool_schemas, indent=1) + "\n")
    stats = {"lessons": len(rows), "per_scenario": per_scenario, "tools": tools,
             "episodes_per_scenario": args.episodes, "detour_p": args.detour, "seed": args.seed,
             "held_out": [s for s in SCENARIOS if s not in TRAIN_SCENARIOS]}  # fmt: skip
    (args.out / "stats.json").write_text(json.dumps(stats, indent=1) + "\n")
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
