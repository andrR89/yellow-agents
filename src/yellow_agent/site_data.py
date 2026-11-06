"""Data exporters for the showcase site (site/data/). Everything the page shows comes from here.

CLI::

    yellow-site-data sessions          # docs/sessions/*.md -> site/data/sessions.json (no ROM)
    yellow-site-data mcp-flow          # real MCP session over stdio -> site/data/mcp_flow.json
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the showcase site's data.")
    parser.add_argument("what", choices=["sessions", "mcp-flow"])
    parser.add_argument("--site", type=Path, default=Path("site"))
    parser.add_argument("--sessions-dir", type=Path, default=Path("docs/sessions"))
    args = parser.parse_args()
    out_dir = args.site / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.what == "sessions":
        sessions = export_sessions(args.sessions_dir)
        payload = [s.model_dump() for s in sessions]
        out = out_dir / "sessions.json"
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
