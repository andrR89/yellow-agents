"""RAM snapshots for the showcase site: raw bytes, which bytes become which field, and the JSON.

The site's "RAM decoder" piece animates hex bytes -> highlighted fields -> the state the model
sees. This module produces that data from real memory, so the animation is never invented.

CLI::

    yellow-snapshot got_pikachu --out site/data/snapshots/got_pikachu.json
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from pydantic import BaseModel

from .gamedata import GameData
from .state import (
    NAME_LENGTH,
    PARTY_LENGTH,
    PARTYMON_STRUCT_LENGTH,
    PM_HP,
    PM_LEVEL,
    PM_MAXHP,
    PM_MOVES,
    PM_PP,
    PM_SPECIES,
    PM_STATUS,
    PM_TYPE1,
    PM_TYPE2,
    SCREEN_COLS,
    SCREEN_ROWS,
    GameState,
    ReadFn,
    StateReader,
)
from .symbols import SymbolTable


class Field(BaseModel):
    offset: int  # from the start of the region
    length: int
    path: str  # where it lands in GameState, e.g. "party[0].hp"
    note: str = ""  # how the bytes are decoded


class Region(BaseModel):
    symbol: str  # pret/pokeyellow symbol the region starts at
    address: int
    hex: str  # raw bytes, lowercase hex
    fields: list[Field]


class Snapshot(BaseModel):
    label: str
    frame: int
    state: GameState
    regions: list[Region]


# (symbol, length, fields) for fixed-size regions
_SCALARS: list[tuple[str, int, list[Field]]] = [
    ("wPlayerName", NAME_LENGTH, [Field(offset=0, length=NAME_LENGTH, path="player_name",
                                        note="Gen 1 charset, 0x50 terminates")]),
    ("wRivalName", NAME_LENGTH, [Field(offset=0, length=NAME_LENGTH, path="rival_name",
                                       note="Gen 1 charset, 0x50 terminates")]),
    ("wCurMap", 1, [Field(offset=0, length=1, path="map_name", note="map id -> name")]),
    ("wYCoord", 1, [Field(offset=0, length=1, path="y")]),
    ("wXCoord", 1, [Field(offset=0, length=1, path="x")]),
    ("wSpritePlayerStateData1FacingDirection", 1,
     [Field(offset=0, length=1, path="facing", note="0 down, 4 up, 8 left, 0xC right")]),
    ("wPlayerMoney", 3, [Field(offset=0, length=3, path="money", note="BCD, 6 digits")]),
    ("wObtainedBadges", 1, [Field(offset=0, length=1, path="badges", note="bit 0 = BOULDER")]),
    ("wPikachuHappiness", 1, [Field(offset=0, length=1, path="pikachu_happiness")]),
    ("wPikachuMood", 1, [Field(offset=0, length=1, path="pikachu_mood")]),
    ("wIsInBattle", 1, [Field(offset=0, length=1, path="battle.kind",
                              note="0 none, 1 wild, 2 trainer, 0xFF lost")]),
    ("wFontLoaded", 1, [Field(offset=0, length=1, path="screen.kind",
                              note="bit 0: font tiles loaded = text box or menu")]),
    ("wTileMap", SCREEN_COLS * SCREEN_ROWS,
     [Field(offset=0, length=SCREEN_COLS * SCREEN_ROWS, path="screen.lines",
            note="20x18 tile ids; font tiles decode to text")]),
]  # fmt: skip

# party_struct fields (macros/ram.asm), relative to one member
_MON_FIELDS: list[tuple[int, int, str, str]] = [
    (PM_SPECIES, 1, "species", "internal index, not Pokédex number"),
    (PM_HP, 2, "hp", "big-endian"),
    (PM_STATUS, 1, "status", "bits 0-2 sleep, 3 psn, 4 brn, 5 frz, 6 par"),
    (PM_TYPE1, 1, "types", "type 1"),
    (PM_TYPE2, 1, "types", "type 2 (same as type 1 = single type)"),
    (PM_MOVES, 4, "moves", "move ids"),
    (PM_PP, 4, "moves", "PP; top 2 bits are PP Ups"),
    (PM_LEVEL, 1, "level", ""),
    (PM_MAXHP, 2, "max_hp", "big-endian"),
]


def export_snapshot(
    read: ReadFn, symbols: SymbolTable, data: GameData, *, label: str, frame: int
) -> Snapshot:
    def region(symbol: str, length: int, fields: list[Field]) -> Region:
        address = symbols.addr(symbol)
        return Region(
            symbol=symbol, address=address, hex=bytes(read(address, length)).hex(), fields=fields
        )

    regions = [region(sym, length, fields) for sym, length, fields in _SCALARS]

    count = min(read(symbols.addr("wPartyCount"), 1)[0], PARTY_LENGTH)
    regions.append(
        region("wPartyCount", 1, [Field(offset=0, length=1, path="party", note="party size")])
    )
    mon_fields = [
        Field(
            offset=i * PARTYMON_STRUCT_LENGTH + off, length=n, path=f"party[{i}].{name}", note=note
        )
        for i in range(count)
        for off, n, name, note in _MON_FIELDS
    ]
    regions.append(region("wPartyMons", count * PARTYMON_STRUCT_LENGTH, mon_fields))
    nick_fields = [
        Field(offset=i * NAME_LENGTH, length=NAME_LENGTH, path=f"party[{i}].nickname")
        for i in range(count)
    ]
    regions.append(region("wPartyMonNicks", count * NAME_LENGTH, nick_fields))

    state = StateReader(read, symbols, data).read()
    return Snapshot(label=label, frame=frame, state=state, regions=regions)


def main() -> None:
    from .emulator import Emulator  # needs PyBoy; keep the module importable without it

    parser = argparse.ArgumentParser(description="Export a RAM snapshot of a save state as JSON.")
    parser.add_argument("save", help="save state name in YELLOW_SAVES (without .state)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--label", help="human-readable label (default: save name)")
    args = parser.parse_args()

    rom = os.environ.get("YELLOW_ROM")
    if not rom or not Path(rom).is_file():
        parser.error("set YELLOW_ROM to your own Pokémon Yellow dump")
    saves = Path(os.environ.get("YELLOW_SAVES", "saves"))
    emu = Emulator(
        rom,
        sym=os.environ.get("YELLOW_SYM", "data/generated/pokeyellow.sym"),
        data_dir=os.environ.get("YELLOW_DATA", "data/generated"),
    )
    emu.load_state(saves / f"{args.save}.state")
    snap = export_snapshot(
        emu._read, emu.symbols, emu.data, label=args.label or args.save, frame=emu.frame
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(snap.model_dump_json(indent=1) + "\n", encoding="utf-8")
    emu.close()
    print(f"wrote {args.out} ({len(snap.regions)} regions)")


if __name__ == "__main__":
    main()
