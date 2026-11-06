"""New game -> Pikachu using only the high-level actions (no raw buttons, no waits).

How many calls the same route takes with `actions.py`, against session 3's 107 MCP calls.

CLI::

    yellow-action-route --site site      # site/data/action_route.json
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .actions import ActionResult, StopReason, advance_text, choose, talk, walk
from .newgame import new_game

if TYPE_CHECKING:
    from .emulator import Emulator

# (direction, tiles) from the bedroom (3,6) to the grass north of Pallet Town; same path as
# baseline.HOUSE_TO_NORTH_EXIT, grouped into walks. The last walk steps into the grass.
HOUSE_TO_GRASS: list[tuple[str, int]] = [
    ("left", 3), ("up", 4), ("right", 6), ("up", 1),  # bedroom -> stairs
    ("down", 5), ("left", 4), ("down", 2),  # living room -> front door
    ("down", 1), ("right", 5), ("up", 6), ("up", 1),  # Pallet Town -> grass
]  # fmt: skip
# Oak's lab, once free at (5,3): face the Poké Ball on the table at (7,3).
LAB_TO_BALL: list[tuple[str, int]] = [("down", 1), ("right", 2), ("up", 1)]
MAX_TEXT_CALLS = 30


@dataclass
class Route:
    results: list[ActionResult] = field(default_factory=list)
    new_game_frame: int = 0

    @property
    def calls(self) -> int:
        return len(self.results)


def _done(r: ActionResult) -> bool:
    has_pikachu = any(m.species == "PIKACHU" for m in r.state.party)
    return has_pikachu and r.stop is StopReason.OVERWORLD


def play_to_pikachu_with_actions(
    emu: Emulator, player_name: str = "CLAUDE", rival_name: str = "GEMINI"
) -> Route:
    route = Route()
    new_game(emu, player_name, rival_name)  # CLAUDE/GEMINI: same as the baseline and MCP run
    route.new_game_frame = emu.frame

    def do(result: ActionResult) -> ActionResult:
        route.results.append(result)
        return result

    for direction, tiles in HOUSE_TO_GRASS:
        do(walk(emu, direction, tiles))
    walked_to_ball = False
    r = do(advance_text(emu))
    for _ in range(MAX_TEXT_CALLS):
        s = r.state
        if _done(r):
            return route
        if r.stop in (StopReason.MENU, StopReason.BATTLE_MENU) and s.screen.cursor:
            # No nickname. Otherwise this is Oak's catch demo: the game moves the cursor
            # itself (ITEM, then POKé BALL) and waits for A, so accept what it picked.
            nickname = any("nickname" in line for line in s.screen.lines)
            r = do(choose(emu, "NO" if nickname else s.screen.cursor))
            continue
        if r.stop is StopReason.OVERWORLD and s.map_name == "OAKS_LAB" and not walked_to_ball:
            walked_to_ball = True
            for direction, tiles in LAB_TO_BALL:
                do(walk(emu, direction, tiles))
            r = do(talk(emu))
            continue
        if r.stop is StopReason.OVERWORLD:
            raise RuntimeError(f"free control at {s.map_name} ({s.x},{s.y}) before Pikachu")
        r = do(advance_text(emu))  # frame cap reached mid-scene: keep going
    raise RuntimeError("actions did not reach the Pikachu")


def main() -> None:
    from .emulator import Emulator

    parser = argparse.ArgumentParser(description="New game -> Pikachu with high-level actions.")
    parser.add_argument("--site", type=Path, help="write data/action_route.json")
    args = parser.parse_args()
    rom = os.environ.get("YELLOW_ROM")
    if not rom or not Path(rom).is_file():
        parser.error("set YELLOW_ROM to your own Pokémon Yellow dump")
    emu = Emulator(
        rom,
        sym=os.environ.get("YELLOW_SYM", "data/generated/pokeyellow.sym"),
        data_dir=os.environ.get("YELLOW_DATA", "data/generated"),
    )
    route = play_to_pikachu_with_actions(emu)
    total = emu.frame
    emu.close()
    summary = {
        "calls": route.calls + 1,  # + new_game, to compare with an MCP run
        "actions": dict(Counter(r.action["tool"] for r in route.results)),
        "total_frames": total,
        "steps": [
            {"action": r.action, "stop": r.stop.value, "frames": r.frames, "presses": r.presses}
            for r in route.results
        ],
    }
    for r in route.results:
        print(f"{r.frames:6d}  {r.stop.value:12} {r.action}")
    print(f"{summary['calls']} calls, frame {summary['total_frames']}")
    if args.site:
        out = args.site / "data" / "action_route.json"
        out.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
