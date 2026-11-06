"""Scripted baseline: power-on -> Pikachu with no model at all, plus the site's data.

This is the yardstick for every agent: the frames a fixed, known-good route needs to reach each
milestone. The same run exports the RAM snapshots for the site's decoder and, optionally, a video.

CLI::

    yellow-baseline --site site             # site/data/baseline.json + site/data/snapshots/
    yellow-baseline --site site --video site/media/baseline.mp4
"""

from __future__ import annotations

import argparse
import os
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from .newgame import new_game
from .recorder import _git_commit
from .snapshot import Snapshot, export_snapshot
from .state import GameState, ScreenKind

if TYPE_CHECKING:
    from .emulator import Emulator

# Bedroom (3,6) -> stairs -> living room -> front door -> Pallet Town north exit (10,1).
# Measured on a fresh game; tests/test_rom.py checks every step's outcome.
HOUSE_TO_NORTH_EXIT: list[str] = (
    ["left"] * 3 + ["up"] * 4 + ["right"] * 6 + ["up"]  # bedroom -> stairs
    + ["down"] * 5 + ["left"] * 4 + ["down"] * 2  # living room -> front door
    + ["down"] + ["right"] * 5 + ["up"] * 6  # Pallet Town -> north exit
)  # fmt: skip
# In Oak's lab, once free: from (5,3) to Oak, then talk. Measured.
LAB_TO_OAK: list[str] = ["down", "right", "right", "up"]
_MAX_SCRIPT_ACTIONS = 600
_IDLE_LIMIT = 8  # waits of 30 frames with input enabled = the player has control
WIDTH, HEIGHT = 160, 144


class Milestone(BaseModel):
    name: str
    frame: int
    map_name: str
    x: int
    y: int


class Baseline(BaseModel):
    player_name: str
    rival_name: str
    total_frames: int
    milestones: list[Milestone]
    git_commit: str | None
    generated_at: datetime


class _Run:
    def __init__(self, emu: Emulator, snapshot_at: set[str]):
        self.emu = emu
        self.milestones: list[Milestone] = []
        self.snapshots: dict[str, Snapshot] = {}
        self._snapshot_at = snapshot_at

    def mark(self, name: str) -> None:
        if any(m.name == name for m in self.milestones):
            return
        s = self.emu.state()
        self.milestones.append(
            Milestone(name=name, frame=self.emu.frame, map_name=s.map_name, x=s.x, y=s.y)
        )
        if name in self._snapshot_at:
            self.snapshots[name] = export_snapshot(
                self.emu._read, self.emu.symbols, self.emu.data, label=name, frame=self.emu.frame
            )


def _has_pikachu(s: GameState) -> bool:
    return any(p.species == "PIKACHU" for p in s.party)


def play_to_pikachu(
    emu: Emulator,
    player_name: str = "CLAUDE",
    rival_name: str = "GEMINI",
    snapshot_at: frozenset[str] = frozenset(),
) -> _Run:
    """Run the scripted route; returns milestones (and snapshots for the names asked)."""
    run = _Run(emu, set(snapshot_at))
    new_game(emu, player_name, rival_name)
    run.mark("bedroom")
    for direction in HOUSE_TO_NORTH_EXIT:
        emu.step(direction)
        if emu.state().map_name == "PALLET_TOWN":
            run.mark("pallet_town")
    run.mark("north_exit")
    emu.step("up")  # into the grass: Oak stops you

    idle, walked = 0, False
    for _ in range(_MAX_SCRIPT_ACTIONS):
        s = emu.state()
        if s.map_name == "OAKS_LAB":
            run.mark("oaks_lab")
        if _has_pikachu(s) and s.screen.kind is ScreenKind.OVERWORLD:
            emu.wait(90)
            run.mark("got_pikachu")
            return run
        if s.screen.kind is ScreenKind.MENU:
            if any("FIGHT" in line for line in s.screen.lines):
                run.mark("oak_battle_menu")
            if s.screen.cursor == "YES" and any("nickname" in line for line in s.screen.lines):
                emu.press("down")  # no nickname
            emu.press("a")
            continue
        if s.screen.kind is ScreenKind.TEXT:
            if s.map_name == "PALLET_TOWN":
                run.mark("oak_stops_you")
            emu.press("a")
            continue
        input_enabled = emu.input_enabled()
        emu.wait(30)
        idle = idle + 1 if input_enabled else 0
        if idle >= _IDLE_LIMIT and s.map_name == "OAKS_LAB" and not walked:
            walked, idle = True, 0
            for direction in LAB_TO_OAK:
                emu.step(direction)
            emu.press("a")
        elif idle >= _IDLE_LIMIT:
            raise RuntimeError(f"stuck with control at {s.map_name} ({s.x},{s.y})")
    raise RuntimeError("baseline did not reach the Pikachu")


def ffmpeg_writer(out: Path, scale: int = 4) -> tuple[Callable, Callable[[], None]]:
    """(on_frame, close): pipe RGBA frames at 60 fps into an H.264 MP4, pixel-perfect scaled."""
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
         "-s", f"{WIDTH}x{HEIGHT}", "-r", "60", "-i", "-",
         "-vf", f"scale={WIDTH * scale}:{HEIGHT * scale}:flags=neighbor",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart",
         str(out)],
        stdin=subprocess.PIPE,
    )  # fmt: skip
    assert proc.stdin is not None
    stdin = proc.stdin

    def on_frame(frame) -> None:
        stdin.write(frame.tobytes())

    def close() -> None:
        stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg failed")

    return on_frame, close


SITE_SNAPSHOTS = frozenset({"bedroom", "oak_stops_you", "oak_battle_menu", "got_pikachu"})


def main() -> None:
    from .emulator import Emulator  # needs PyBoy; keep the module importable without it

    parser = argparse.ArgumentParser(description="Scripted baseline run to the Pikachu.")
    parser.add_argument("--site", type=Path, help="write data/baseline.json + data/snapshots/")
    parser.add_argument("--video", type=Path, help="also record every frame to this MP4")
    parser.add_argument("--player", default="CLAUDE")
    parser.add_argument("--rival", default="GEMINI")
    args = parser.parse_args()

    rom = os.environ.get("YELLOW_ROM")
    if not rom or not Path(rom).is_file():
        parser.error("set YELLOW_ROM to your own Pokémon Yellow dump")
    emu = Emulator(
        rom,
        sym=os.environ.get("YELLOW_SYM", "data/generated/pokeyellow.sym"),
        data_dir=os.environ.get("YELLOW_DATA", "data/generated"),
    )
    close_video = None
    if args.video:
        emu.on_frame, close_video = ffmpeg_writer(args.video)
    run = play_to_pikachu(
        emu, args.player, args.rival, SITE_SNAPSHOTS if args.site else frozenset()
    )
    if close_video:
        close_video()
    emu.close()

    baseline = Baseline(
        player_name=args.player,
        rival_name=args.rival,
        total_frames=run.milestones[-1].frame,
        milestones=run.milestones,
        git_commit=_git_commit(),
        generated_at=datetime.now(UTC),
    )
    for m in run.milestones:
        print(f"{m.frame:6d}  {m.name:16} {m.map_name}({m.x},{m.y})")
    if args.site:
        data = args.site / "data"
        (data / "snapshots").mkdir(parents=True, exist_ok=True)
        (data / "baseline.json").write_text(baseline.model_dump_json(indent=1) + "\n")
        for name, snap in run.snapshots.items():
            (data / "snapshots" / f"{name}.json").write_text(snap.model_dump_json(indent=1) + "\n")
        print(f"wrote {data}/baseline.json and {len(run.snapshots)} snapshots")


if __name__ == "__main__":
    main()
