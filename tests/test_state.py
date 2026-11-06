from yellow_agent.state import (
    PARTYMON_STRUCT_LENGTH,
    BattleKind,
    StateReader,
    decode_bcd,
    decode_status,
)
from yellow_agent.text import encode


def _write_pikachu(memory, symbols):
    base = symbols.addr("wPartyMons")
    memory.poke(symbols.addr("wPartyCount"), [1])
    memory.poke(base + 0x00, [0x54])  # species: PIKACHU (internal index)
    memory.poke(base + 0x01, [0x00, 0x13])  # HP 19
    memory.poke(base + 0x05, [0x17, 0x17])  # ELECTRIC / ELECTRIC
    memory.poke(base + 0x08, [0x54, 0x2D, 0, 0])  # THUNDERSHOCK, GROWL
    memory.poke(base + 0x1D, [30, 0x40 | 40, 0, 0])  # PP (2nd has one PP Up bit set)
    memory.poke(base + 0x21, [5])  # level
    memory.poke(base + 0x22, [0x00, 0x14])  # max HP 20
    memory.poke(symbols.addr("wPartyMonNicks"), encode("PIKACHU"))


def test_overworld_state(memory, symbols, gamedata):
    s = symbols
    memory.poke(s.addr("wPlayerName"), encode("ANDRE"))
    memory.poke(s.addr("wRivalName"), encode("GARY"))
    memory.poke(s.addr("wCurMap"), [0x28])
    memory.poke(s.addr("wXCoord"), [5])
    memory.poke(s.addr("wYCoord"), [3])
    memory.poke(s.addr("wSpritePlayerStateData1FacingDirection"), [0x04])  # up
    memory.poke(s.addr("wPlayerMoney"), [0x00, 0x30, 0x00])  # BCD 3000
    memory.poke(s.addr("wObtainedBadges"), [0b0000_0001])
    memory.poke(s.addr("wPikachuHappiness"), [90])
    _write_pikachu(memory, s)

    state = StateReader(memory.read, s, gamedata).read()

    assert state.player_name == "ANDRE"
    assert state.rival_name == "GARY"
    assert state.map_name == "OAKS_LAB"
    assert (state.x, state.y, state.facing) == (5, 3, "up")
    assert state.money == 3000
    assert state.badges == ["BOULDER"]
    assert state.pikachu_happiness == 90
    assert state.battle.kind is BattleKind.NONE

    (pika,) = state.party
    assert pika.species == "PIKACHU"
    assert pika.nickname == "PIKACHU"
    assert (pika.level, pika.hp, pika.max_hp) == (5, 19, 20)
    assert pika.types == ["ELECTRIC"]
    assert [(m.name, m.pp) for m in pika.moves] == [("THUNDERSHOCK", 30), ("GROWL", 40)]


def test_party_count_is_clamped(memory, symbols, gamedata):
    memory.poke(symbols.addr("wPartyCount"), [0xFF])  # garbage during intro
    assert len(StateReader(memory.read, symbols, gamedata).party()) == 6
    assert PARTYMON_STRUCT_LENGTH == 44


def test_trainer_battle_reads_both_mons(memory, symbols, gamedata):
    memory.poke(symbols.addr("wIsInBattle"), [2])
    enemy = symbols.addr("wEnemyMon")
    memory.poke(enemy + 0x00, [0x66])  # EEVEE
    memory.poke(enemy + 0x01, [0x00, 0x0A])
    memory.poke(enemy + 0x05, [0x00, 0x00])
    memory.poke(enemy + 0x08, [0x21, 0x1C, 0, 0])
    memory.poke(enemy + 0x0E, [5])
    memory.poke(enemy + 0x0F, [0x00, 0x14])
    memory.poke(enemy + 0x19, [35, 15, 0, 0])

    battle = StateReader(memory.read, symbols, gamedata).battle()

    assert battle.kind is BattleKind.TRAINER
    assert battle.enemy_mon.species == "EEVEE"
    assert battle.enemy_mon.level == 5
    assert [m.name for m in battle.enemy_mon.moves] == ["TACKLE", "SAND-ATTACK"]


def test_helpers():
    assert decode_bcd([0x12, 0x34, 0x56]) == 123456
    assert decode_status(0) == "ok"
    assert decode_status(0b011) == "asleep"
    assert decode_status(1 << 6) == "paralyzed"


def test_empty_battle_slot_is_none(memory, symbols, gamedata):
    # Oak's scripted Pikachu catch: a wild battle where the player has no Pokémon out.
    memory.poke(symbols.addr("wIsInBattle"), [1])
    memory.poke(symbols.addr("wEnemyMon"), [0x54])
    battle = StateReader(memory.read, symbols, gamedata).battle()
    assert battle.player_mon is None
    assert battle.enemy_mon is not None and battle.enemy_mon.species == "PIKACHU"
