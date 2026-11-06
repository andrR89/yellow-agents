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
from .text import decode

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
DIRECTIONS = {1: "right", 2: "left", 4: "down", 8: "up"}


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
        return [
            self._mon(
                mons_base + i * PARTYMON_STRUCT_LENGTH,
                battle=False,
                nickname=self._name_at(nicks_base + i * NAME_LENGTH),
            )
            for i in range(count)
        ]

    def battle(self) -> Battle:
        raw = self._u8(self._sym.addr("wIsInBattle"))
        battle_kind = _BATTLE_KINDS.get(raw, BattleKind.NONE)
        if battle_kind in (BattleKind.NONE, BattleKind.LOST):
            return Battle(kind=battle_kind)
        return Battle(
            kind=battle_kind,
            player_mon=self._mon(self._sym.addr("wBattleMon"), battle=True),
            enemy_mon=self._mon(self._sym.addr("wEnemyMon"), battle=True),
        )

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
            facing=DIRECTIONS.get(self._u8(s.addr("wPlayerDirection")), "unknown"),
            money=decode_bcd(self._read(s.addr("wPlayerMoney"), 3)),
            badges=[b for i, b in enumerate(BADGES) if badge_bits & (1 << i)],
            pikachu_happiness=self._u8(s.addr("wPikachuHappiness")),
            pikachu_mood=self._u8(s.addr("wPikachuMood")),
            party=self.party(),
            battle=self.battle(),
        )
