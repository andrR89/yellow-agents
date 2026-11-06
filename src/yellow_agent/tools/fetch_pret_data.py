"""Download pokeyellow.sym and extract game data tables from pret/pokeyellow.

Everything lands in data/generated/ (git-ignored). Run once after cloning:

    yellow-fetch-data                 # download from GitHub
    yellow-fetch-data --local ../pokeyellow   # use a local clone instead

Outputs:
    pokeyellow.sym      RAM/ROM symbols (from the `symbols` branch)
    pokemon.json        internal species index -> name   (NOT Pokédex number)
    moves.json          move id -> name
    maps.json           map id -> constant name (+ width/height in blocks)
    types.json          type id -> name
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path

RAW = "https://raw.githubusercontent.com/pret/pokeyellow/{branch}/{path}"

SOURCES = {
    "sym": ("symbols", "pokeyellow.sym"),
    "pokemon": ("master", "data/pokemon/names.asm"),
    "moves": ("master", "data/moves/names.asm"),
    "maps": ("master", "constants/map_constants.asm"),
    "types": ("master", "constants/type_constants.asm"),
}

DEFAULT_OUT = Path("data/generated")


def _read(key: str, local: Path | None) -> str:
    branch, path = SOURCES[key]
    if local is not None:
        candidate = local / path
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
        if key != "sym":
            raise FileNotFoundError(candidate)
        # .sym only exists after `make`; fall through to download
    with urllib.request.urlopen(RAW.format(branch=branch, path=path), timeout=30) as resp:
        return resp.read().decode("utf-8")


def parse_indexed_strings(asm: str, macro: str) -> dict[int, str]:
    """`dname "RHYDON"` / `li "POUND"` lists, 1-based in file order."""
    names = re.findall(rf'^\s*{macro}\s+"([^"]*)"', asm, flags=re.MULTILINE)
    return {i + 1: name for i, name in enumerate(names)}


def parse_maps(asm: str) -> dict[int, dict]:
    pattern = re.compile(
        r"^\s*map_const\s+(\w+),\s*(\d+),\s*(\d+)\s*;\s*\$([0-9A-Fa-f]+)", re.MULTILINE
    )
    return {
        int(h, 16): {"name": name, "width": int(w), "height": int(hgt)}
        for name, w, hgt, h in pattern.findall(asm)
    }


def parse_types(asm: str) -> dict[int, str]:
    pattern = re.compile(r"^\s*const\s+(\w+)\s*;\s*\$([0-9A-Fa-f]+)", re.MULTILINE)
    return {int(h, 16): name.removesuffix("_TYPE") for name, h in pattern.findall(asm)}


def fetch(out: Path = DEFAULT_OUT, local: Path | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "pokeyellow.sym").write_text(_read("sym", local), encoding="utf-8")
    tables = {
        "pokemon": parse_indexed_strings(_read("pokemon", local), "dname"),
        "moves": parse_indexed_strings(_read("moves", local), "li"),
        "maps": parse_maps(_read("maps", local)),
        "types": parse_types(_read("types", local)),
    }
    for name, table in tables.items():
        if not table:
            raise RuntimeError(f"parsed 0 entries for {name} — upstream format changed?")
        (out / f"{name}.json").write_text(json.dumps(table, indent=1, ensure_ascii=False))
        print(f"{name:8s} {len(table):4d} entries")
    print(f"written to {out.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--local", type=Path, help="path to a local pret/pokeyellow clone")
    args = parser.parse_args()
    fetch(args.out, args.local)


if __name__ == "__main__":
    main()
