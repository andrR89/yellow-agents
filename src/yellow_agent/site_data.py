"""Data exporters for the showcase site (site/data/). Everything the page shows comes from here.

CLI::

    yellow-site-data sessions          # docs/sessions/*.md -> site/data/sessions.json (no ROM)
    yellow-site-data mcp-flow          # real MCP session over stdio -> site/data/mcp_flow.json
    yellow-site-data run runs/<id>     # recorded run -> site/data/runs/<id>.json + screens (no ROM)
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.S)
_SESSION_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}\.md$")


class Session(BaseModel):
    file: str
    meta: dict[str, Any]
    body: str  # markdown, pt-BR


def _scalar(value: str) -> Any:
    value = value.strip()
    if value in ("null", "~", ""):
        return None
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        return [_scalar(v) for v in value[1:-1].split(",") if v.strip()]
    for kind in (int, float):
        try:
            return kind(value)
        except ValueError:
            pass
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """The flat `key: value` frontmatter of docs/sessions/README.md (no nesting needed)."""
    match = _FRONTMATTER.match(text)
    if not match:
        raise ValueError("missing --- frontmatter ---")
    meta: dict[str, Any] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        if value.strip().startswith('"'):
            value = value.strip().split('"', 2)
            meta[key.strip()] = value[1]
            continue
        meta[key.strip()] = _scalar(value.split(" #", 1)[0])
    return meta, match.group(2).strip() + "\n"


def export_sessions(sessions_dir: Path) -> list[Session]:
    out = []
    for path in sorted(sessions_dir.iterdir()):
        if _SESSION_FILE.match(path.name):
            meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            out.append(Session(file=path.name, meta=meta, body=body))
    return out


# -- MCP flow ----------------------------------------------------------------

_STATE_KEYS = ("player_name", "rival_name", "map_name", "x", "y", "facing", "screen")


class McpCall(BaseModel):
    tool: str
    arguments: dict[str, Any]
    is_error: bool
    latency_ms: float  # wall clock, client side: includes emulation
    result: Any  # trimmed: the fields the animation shows


def _trim(content: list[Any]) -> Any:
    item = content[0]
    if item.type == "image":
        return {"image": item.mime_type, "file": "media/mcp_screenshot.png"}
    text = item.text
    try:
        data = json.loads(text)
    except ValueError:
        return text
    if isinstance(data, dict) and "map_name" in data:
        return {k: data[k] for k in _STATE_KEYS} | {"party": len(data["party"])}
    return data


async def record_mcp_flow(env: dict[str, str], media_dir: Path) -> list[McpCall]:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    script = [
        ("new_game", {"player_name": "CLAUDE"}),
        ("press_buttons", {"buttons": ["left", "left", "up"]}),
        ("screenshot", {}),
        ("press_buttons", {"buttons": ["jump"]}),
    ]
    server = StdioServerParameters(
        command=sys.executable, args=["-m", "yellow_agent.mcp_server"], env=env
    )
    calls = []
    async with stdio_client(server) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        for tool, arguments in script:
            t0 = time.perf_counter()
            res = await session.call_tool(tool, arguments)
            latency = (time.perf_counter() - t0) * 1000
            if res.content and res.content[0].type == "image":
                media_dir.mkdir(parents=True, exist_ok=True)
                (media_dir / "mcp_screenshot.png").write_bytes(
                    base64.b64decode(res.content[0].data)
                )
            calls.append(
                McpCall(
                    tool=tool,
                    arguments=arguments,
                    is_error=res.is_error,
                    latency_ms=round(latency, 1),
                    result=_trim(res.content),
                )
            )
    return calls


# -- recorded runs -> replay --------------------------------------------------


class ReplayStep(BaseModel):
    index: int
    frame: int
    action: dict[str, Any]
    map_name: str
    x: int
    y: int
    facing: str
    screen: dict[str, Any]
    party: list[str]  # "PIKACHU Lv5"
    battle: str
    screenshot: str | None  # path relative to site/


class Replay(BaseModel):
    run_id: str
    source: str
    player_name: str
    rival_name: str
    started_at: str
    git_commit: str | None
    start_frame: int  # frame when the first recorded action returned
    total_frames: int  # frame of the got_pikachu milestone (same clock as the baseline)
    actions: dict[str, int]  # tool -> count
    wait_frames: int  # frames spent inside `wait` calls
    milestones: list[dict[str, Any]]
    steps: list[ReplayStep]


def run_milestones(steps: list[Any]) -> list[dict[str, Any]]:
    """The baseline's milestones, found in a recorded run.

    Same rules as `baseline.play_to_pikachu`, but a run only has the state after each tool call,
    so a milestone lands on the first call whose resulting state shows it (coarser than the
    baseline, which checks after every single press).
    """
    rules: list[tuple[str, Any]] = [
        ("bedroom", lambda s: s.map_name == "REDS_HOUSE_2F"),
        ("pallet_town", lambda s: s.map_name == "PALLET_TOWN"),
        ("north_exit", lambda s: s.map_name == "PALLET_TOWN" and s.y <= 1),
        ("oak_stops_you", lambda s: s.map_name == "PALLET_TOWN" and s.screen.kind == "text"),
        (
            "oak_battle_menu",
            lambda s: s.screen.kind == "menu" and any("FIGHT" in ln for ln in s.screen.lines),
        ),
        ("oaks_lab", lambda s: s.map_name == "OAKS_LAB"),
        (
            "got_pikachu",
            lambda s: s.screen.kind == "overworld" and any(p.species == "PIKACHU" for p in s.party),
        ),
    ]
    out = []
    for name, rule in rules:
        hit = next((st for st in steps if rule(st.state)), None)
        if hit is not None:
            s = hit.state
            out.append(
                {"name": name, "frame": hit.frame, "step": hit.index, "map_name": s.map_name}
                | {"x": s.x, "y": s.y}
            )
    return out


def export_run(run_dir: Path, site: Path) -> Replay:
    from .recorder import load_run

    header, steps = load_run(run_dir)
    if not steps:
        raise ValueError(f"{run_dir}: no steps")
    media = site / "media" / "runs" / header.run_id
    media.mkdir(parents=True, exist_ok=True)
    out_steps = []
    actions: dict[str, int] = {}
    wait_frames = 0
    for st in steps:
        tool = str(st.action.get("tool"))
        actions[tool] = actions.get(tool, 0) + 1
        if tool == "wait":
            wait_frames += int(st.action.get("frames", 0))
        shot = None
        if st.screenshot:
            name = Path(st.screenshot).name
            shutil.copyfile(run_dir / st.screenshot, media / name)
            shot = f"media/runs/{header.run_id}/{name}"
        s = st.state
        out_steps.append(
            ReplayStep(
                index=st.index,
                frame=st.frame,
                action=st.action,
                map_name=s.map_name,
                x=s.x,
                y=s.y,
                facing=s.facing,
                screen=s.screen.model_dump(mode="json"),
                party=[f"{p.species} Lv{p.level}" for p in s.party],
                battle=str(s.battle.kind),
                screenshot=shot,
            )
        )
    milestones = run_milestones(steps)
    last = next((m for m in milestones if m["name"] == "got_pikachu"), None)
    first = steps[0].state
    return Replay(
        run_id=header.run_id,
        source=header.source,
        player_name=first.player_name,
        rival_name=first.rival_name,
        started_at=header.started_at.isoformat(),
        git_commit=header.git_commit,
        start_frame=steps[0].frame,
        total_frames=last["frame"] if last else steps[-1].frame,
        actions=actions,
        wait_frames=wait_frames,
        milestones=milestones,
        steps=out_steps,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the showcase site's data.")
    parser.add_argument("what", choices=["sessions", "mcp-flow", "run"])
    parser.add_argument("run_dir", nargs="?", type=Path, help="for `run`: runs/<id>")
    parser.add_argument("--site", type=Path, default=Path("site"))
    parser.add_argument("--sessions-dir", type=Path, default=Path("docs/sessions"))
    args = parser.parse_args()
    out_dir = args.site / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.what == "sessions":
        sessions = export_sessions(args.sessions_dir)
        payload = [s.model_dump() for s in sessions]
        out = out_dir / "sessions.json"
    elif args.what == "run":
        if args.run_dir is None:
            parser.error("run: give the run directory, e.g. runs/20261106-183217")
        replay = export_run(args.run_dir, args.site)
        (out_dir / "runs").mkdir(exist_ok=True)
        out = out_dir / "runs" / f"{replay.run_id}.json"
        out.write_text(replay.model_dump_json(indent=1) + "\n", encoding="utf-8")
        index = sorted(p.stem for p in (out_dir / "runs").glob("*.json") if p.stem != "index")
        (out_dir / "runs" / "index.json").write_text(json.dumps(index) + "\n", encoding="utf-8")
        for m in replay.milestones:
            print(f"{m['frame']:6d}  {m['name']:16} step {m['step']}")
        print(f"wrote {out} ({len(replay.steps)} steps)")
        return
    else:
        import anyio

        rom = os.environ.get("YELLOW_ROM")
        if not rom or not Path(rom).is_file():
            parser.error("set YELLOW_ROM to your own Pokémon Yellow dump")
        env = {k: v for k, v in os.environ.items() if k != "YELLOW_RUNS"}  # don't record
        calls = anyio.run(record_mcp_flow, env, args.site / "media")
        payload = [c.model_dump() for c in calls]
        out = out_dir / "mcp_flow.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(payload)} entries)")


if __name__ == "__main__":
    main()
