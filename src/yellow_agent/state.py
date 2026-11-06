"""Read a structured, LLM-friendly game state straight from Pokémon Yellow's RAM.

All addresses come from pret/pokeyellow's .sym file; struct layouts mirror
macros/ram.asm (party_struct / battle_struct). Nothing here depends on PyBoy:
the reader only needs a ``read(address, length) -> list[int]`` function, which
keeps it unit-testable with a fake memory.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel

from .gamedata import GameData
from .symbols import SymbolTable
from .text import BOX_TILES, CURSOR, CURSOR_IDLE, MORE_TEXT, decode, glyph

ReadFn = Callable[[int, int], list[int]]

NAME_LENGTH = 11
PARTY_LENGTH = 6
PARTYMON_STRUCT_LENGTH = 0x2C

# party_struct offsets (macros/ram.asm -> box_struct + party fields)
PM_SPECIES, PM_HP, PM_STATUS, PM_TYPE1, PM_TYPE2 = 0x00, 0x01, 0x04, 0x05, 0x06
PM_MOVES, PM_PP, PM_LEVEL, PM_MAXHP = 0x08, 0x1D, 0x21, 0x22

# battle_struct offsets
BM_SPECIES, BM_HP, BM_STATUS, BM_TYPE1, BM_TYPE2 = 0x00, 0x01, 0x04, 0x05, 0x06
BM_MOVES, BM_LEVEL, BM_MAXHP, BM_PP = 0x08, 0x0E, 0x0F, 0x19

BADGES = ["BOULDER", "CASCADE", "THUNDER", "RAINBOW", "SOUL", "MARSH", "VOLCANO", "EARTH"]
# SPRITE_FACING_* (constants/sprite_data_constants.asm). Read from the player's sprite
# (wSpritePlayerStateData1FacingDirection) because wPlayerDirection stays 0 until the first step
# after loading a save.
FACING = {0x00: "down", 0x04: "up", 0x08: "left", 0x0C: "right"}

# wTileMap: 20x18 background tile buffer (SCREEN_WIDTH x SCREEN_HEIGHT, constants/gfx_constants.asm)
SCREEN_COLS, SCREEN_ROWS = 20, 18
BOX_TOP_LEFT, BOX_BOTTOM_RIGHT = 0x79, 0x7E


class ScreenKind(StrEnum):
    OVERWORLD = "overworld"  # free to walk
    TEXT = "text"  # dialogue / message box: press A to advance
    MENU = "menu"  # a ▶ cursor is on screen: move it, A to choose, B to back out
    CUTSCENE = "cutscene"  # title, intro, transitions: no player sprite yet; A/Start or wait


class BattleKind(StrEnum):
    NONE = "none"
    WILD = "wild"
    TRAINER = "trainer"
    LOST = "lost"


_BATTLE_KINDS = {
    0: BattleKind.NONE,
    1: BattleKind.WILD,
    2: BattleKind.TRAINER,
    0xFF: BattleKind.LOST,
}


class Move(BaseModel):
    name: str
    pp: int


class Mon(BaseModel):
    species: str
    nickname: str | None = None
    level: int
    hp: int
    max_hp: int
    status: str
    types: list[str]
    moves: list[Move]


class Battle(BaseModel):
    kind: BattleKind
    player_mon: Mon | None = None
    enemy_mon: Mon | None = None


class Screen(BaseModel):
    kind: ScreenKind
    lines: list[str]  # visible text, top to bottom; side-by-side boxes joined with " | "
    cursor: str | None = None  # menu item under ▶


class GameState(BaseModel):
    player_name: str
    rival_name: str
    map_id: int
    map_name: str
    x: int
    y: int
    facing: str
    money: int
    badges: list[str]
    pikachu_happiness: int
    pikachu_mood: int
    party: list[Mon]
    battle: Battle
    screen: Screen


def decode_status(byte: int) -> str:
    if byte & 0x07:
        return "asleep"
    for bit, name in ((3, "poisoned"), (4, "burned"), (5, "frozen"), (6, "paralyzed")):
        if byte & (1 << bit):
            return name
    return "ok"


def decode_bcd(data: list[int]) -> int:
    value = 0
    for byte in data:
        value = value * 100 + (byte >> 4) * 10 + (byte & 0x0F)
    return value


def _row_segments(row: list[int]) -> list[str]:
    """Runs of text in one tile row, split at box borders and non-font tiles."""
    out: list[str] = []
    buf = ""
    for tile in [*row, BOX_TOP_LEFT]:  # sentinel flushes the last run
        ch = " " if tile in (CURSOR, CURSOR_IDLE, MORE_TEXT) else glyph(tile)
        if ch is None or tile in BOX_TILES:
            if text := " ".join(buf.split()):
                out.append(text)
            buf = ""
        else:
            buf += ch
    return out


def _item_after_cursor(row: list[int]) -> str:
    """Text right after ▶, up to a border, a non-font tile or a double space."""
    item = ""
    for tile in row[row.index(CURSOR) + 1 :]:
        ch = glyph(tile)
        if ch is None or tile in BOX_TILES or (ch == " " and item.endswith(" ")):
            break
        item += ch
    return item.strip()


def read_screen(tiles: list[int], *, font_loaded: bool, player_loaded: bool) -> Screen:
    """What is on screen, from wTileMap. Pure function: no emulator needed."""
    has_box = BOX_TOP_LEFT in tiles and BOX_BOTTOM_RIGHT in tiles
    if not (font_loaded or has_box):
        kind = ScreenKind.OVERWORLD if player_loaded else ScreenKind.CUTSCENE
        return Screen(kind=kind, lines=[])
    lines: list[str] = []
    cursor: str | None = None
    for r in range(SCREEN_ROWS):
        row = tiles[r * SCREEN_COLS : (r + 1) * SCREEN_COLS]
        if segments := _row_segments(row):
            lines.append(" | ".join(segments))
        if cursor is None and CURSOR in row:
            cursor = _item_after_cursor(row)
    kind = ScreenKind.MENU if cursor is not None else ScreenKind.TEXT
    return Screen(kind=kind, lines=lines, cursor=cursor)


class StateReader:
    def __init__(self, read: ReadFn, symbols: SymbolTable, data: GameData | None = None):
        self._read = read
        self._sym = symbols
        self._data = data or GameData()

    # -- low level -----------------------------------------------------------
    def _u8(self, addr: int) -> int:
        return self._read(addr, 1)[0]

    def _u16be(self, addr: int) -> int:
        hi, lo = self._read(addr, 2)
        return (hi << 8) | lo

    def _name_at(self, addr: int) -> str:
        return decode(self._read(addr, NAME_LENGTH))

    # -- structs -------------------------------------------------------------
    def _mon(self, base: int, *, battle: bool, nickname: str | None = None) -> Mon:
        if battle:
            o_level, o_maxhp, o_pp = BM_LEVEL, BM_MAXHP, BM_PP
        else:
            o_level, o_maxhp, o_pp = PM_LEVEL, PM_MAXHP, PM_PP
        move_ids = self._read(base + PM_MOVES, 4)  # same offset in both structs
        pps = self._read(base + o_pp, 4)
        moves = [
            Move(name=self._data.move(mid) or "", pp=pp & 0x3F)  # top 2 bits = PP Ups
            for mid, pp in zip(move_ids, pps, strict=True)
            if mid != 0
        ]
        type1, type2 = self._u8(base + PM_TYPE1), self._u8(base + PM_TYPE2)
        types = [self._data.type_name(type1)]
        if type2 != type1:
            types.append(self._data.type_name(type2))
        return Mon(
            species=self._data.species(self._u8(base + PM_SPECIES)),
            nickname=nickname,
            level=self._u8(base + o_level),
            hp=self._u16be(base + PM_HP),
            max_hp=self._u16be(base + o_maxhp),
            status=decode_status(self._u8(base + PM_STATUS)),
            types=types,
            moves=moves,
        )

    def party(self) -> list[Mon]:
        count = min(self._u8(self._sym.addr("wPartyCount")), PARTY_LENGTH)
        mons_base = self._sym.addr("wPartyMons")
        nicks_base = self._sym.addr("wPartyMonNicks")
        party = []
        for i in range(count):
            base = mons_base + i * PARTYMON_STRUCT_LENGTH
            if self._u8(base + PM_SPECIES) == 0:  # count bumped, struct not written yet
                continue
            nickname = self._name_at(nicks_base + i * NAME_LENGTH)
            party.append(self._mon(base, battle=False, nickname=nickname))
        return party

    def battle(self) -> Battle:
        raw = self._u8(self._sym.addr("wIsInBattle"))
        battle_kind = _BATTLE_KINDS.get(raw, BattleKind.NONE)
        if battle_kind in (BattleKind.NONE, BattleKind.LOST):
            return Battle(kind=battle_kind)
        return Battle(
            kind=battle_kind,
            player_mon=self._battle_mon("wBattleMon"),
            enemy_mon=self._battle_mon("wEnemyMon"),
        )

    def _battle_mon(self, symbol: str) -> Mon | None:
        base = self._sym.addr(symbol)
        if self._u8(base + BM_SPECIES) == 0:  # empty slot (e.g. Oak's scripted catch)
            return None
        return self._mon(base, battle=True)

    def read(self) -> GameState:
        s = self._sym
        badge_bits = self._u8(s.addr("wObtainedBadges"))
        map_id = self._u8(s.addr("wCurMap"))
        return GameState(
            player_name=self._name_at(s.addr("wPlayerName")),
            rival_name=self._name_at(s.addr("wRivalName")),
            map_id=map_id,
            map_name=self._data.map_name(map_id),
            x=self._u8(s.addr("wXCoord")),
            y=self._u8(s.addr("wYCoord")),
            facing=FACING.get(
                self._u8(s.addr("wSpritePlayerStateData1FacingDirection")), "unknown"
            ),
            money=decode_bcd(self._read(s.addr("wPlayerMoney"), 3)),
            badges=[b for i, b in enumerate(BADGES) if badge_bits & (1 << i)],
            pikachu_happiness=self._u8(s.addr("wPikachuHappiness")),
            pikachu_mood=self._u8(s.addr("wPikachuMood")),
            party=self.party(),
            battle=self.battle(),
            screen=self.screen(),
        )

    def screen(self) -> Screen:
        tiles = self._read(self._sym.addr("wTileMap"), SCREEN_COLS * SCREEN_ROWS)
        font_loaded = bool(self._u8(self._sym.addr("wFontLoaded")) & 1)  # bit 0, ram/wram.asm
        # Player sprite picture is 0 on the title screen and during Oak's intro.
        player_loaded = self._u8(self._sym.addr("wSpritePlayerStateData1PictureID")) != 0
        return read_screen(tiles, font_loaded=font_loaded, player_loaded=player_loaded)
