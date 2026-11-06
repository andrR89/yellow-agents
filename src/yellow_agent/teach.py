"""Lessons for the local model: (prompt, right tool call) pairs from a scripted expert.

The expert plays the training scenarios with the same tools and sees the same prompt the agent
loop builds (goal, trimmed state, last actions). To show the model more than one path, the
expert sometimes takes a random detour of 1-3 tiles; the detour itself is NOT a lesson, but
getting back on track with go_to is (the prompt shows the detour in RECENT ACTIONS). No API
calls, no cost.

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
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .actions import ActionError, is_battle_menu
from .agent import SYSTEM, TOOLS, HistoryItem, build_prompt, describe, execute
from .models.base import ToolCall
from .scenarios import SCENARIOS
from .state import GameState, ScreenKind

if TYPE_CHECKING:
    from .emulator import Emulator

TRAIN_SCENARIOS = ("pikachu", "rival_battle")  # route1 stays out: the held-out test
DELTA = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
PLAYER_NAMES = ("CLAUDE", "QWEN", "GPT", "ASH", "RED", "YELLOW", "AGENT")


# Where the expert goes on each map, with go_to (coordinates checked on the ROM, sessions 4-8).
BEDROOM_STAIRS = (7, 1)
HOUSE_DOOR_MAT = (3, 7)  # go_to walks out through it
PALLET_NORTH_EXIT = (10, 1)  # then one step up into the grass: Oak stops you
BELOW_THE_BALL = (7, 4)  # Oak's lab: face up and talk to take the Poké Ball
LAB_EXIT = (4, 11)  # with Pikachu: on the way out, GEMINI stops you


def _go(xy: tuple[int, int], why: str) -> ToolCall:
    return ToolCall("go_to", {"x": xy[0], "y": xy[1], "reason": why})


def expert_call(state: GameState, in_battle: bool) -> ToolCall:
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
    here = (state.x, state.y)
    has_pikachu = any(m.species == "PIKACHU" for m in state.party)
    match state.map_name:
        case "REDS_HOUSE_2F":
            return _go(BEDROOM_STAIRS, "Take the stairs at the top right of the bedroom.")
        case "REDS_HOUSE_1F":
            return _go(HOUSE_DOOR_MAT, "Leave the house through the front door mat.")
        case "PALLET_TOWN" if not has_pikachu:
            if here == PALLET_NORTH_EXIT:
                grass = "Step into the tall grass north of town."
                return ToolCall("walk", {"direction": "up", "tiles": 1, "reason": grass})
            return _go(PALLET_NORTH_EXIT, "Head to the north edge of Pallet Town.")
        case "OAKS_LAB" if not has_pikachu:
            if here == BELOW_THE_BALL and state.facing == "up":
                return ToolCall("talk", {"reason": "Take the Poké Ball on the table above me."})
            if here == BELOW_THE_BALL:
                return ToolCall("walk", {"direction": "up", "tiles": 1,
                                         "reason": "Face the Poké Ball on the table."})  # fmt: skip
            return _go(BELOW_THE_BALL, "Stand right below the Poké Ball on the table.")
        case "OAKS_LAB":
            return _go(LAB_EXIT, "Head for the lab's exit; GEMINI will challenge me.")
    return ToolCall("advance_text", {"reason": "Wait for the scene to go on."})


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


def episode(emu: Emulator, scenario_name: str, rng: random.Random,
            detour_p: float) -> Iterator[dict[str, Any]]:  # fmt: skip
    """Play one training scenario with the expert. A random detour (1-3 tiles) is not a lesson;
    every expert call after it is, so the model also learns to get back on track."""
    scenario = SCENARIOS[scenario_name]
    scenario.setup(emu, rng.choice(PLAYER_NAMES))
    judge = scenario.judge()
    history: list[HistoryItem] = []
    for turn in range(1, scenario.max_turns + 1):
        state = emu.state()
        prompt = build_prompt(scenario.goal, turn, scenario.max_turns, state, history,
                              emu.map_grid())  # fmt: skip
        detour = (
            state.screen.kind is ScreenKind.OVERWORLD
            and emu.input_enabled()
            and rng.random() < detour_p
        )
        if detour:
            call = ToolCall(
                "walk", {"direction": rng.choice(list(DELTA)), "tiles": rng.randint(1, 3)}
            )
        else:
            call = expert_call(state, emu.in_battle())
            yield lesson(prompt, call)
        try:
            result = execute(emu, call)
        except ActionError as err:
            history.append(
                HistoryItem(turn, {"tool": call.name, **call.arguments}, f"ERROR: {err}")
            )
            continue
        history.append(HistoryItem(turn, result.action, describe(result)))
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

    rng = random.Random(args.seed)
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    tools: Counter[str] = Counter()
    per_scenario: Counter[str] = Counter()
    for scenario in TRAIN_SCENARIOS:
        for i in range(args.episodes):
            emu = emulator()
            try:
                for row in episode(emu, scenario, rng, args.detour if i else 0.0):
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
