"""RAM snapshots for the site's decoder: raw bytes + which bytes become which JSON field."""

from yellow_agent.snapshot import export_snapshot
from yellow_agent.state import StateReader
from yellow_agent.text import encode

from .test_state import _write_pikachu


def test_snapshot_bytes_and_fields_match_the_state(memory, symbols, gamedata):
    memory.poke(symbols.addr("wPlayerName"), encode("YELLOW"))
    memory.poke(symbols.addr("wXCoord"), [5])
    memory.poke(symbols.addr("wPlayerMoney"), [0x00, 0x30, 0x00])
    _write_pikachu(memory, symbols)

    snap = export_snapshot(memory.read, symbols, gamedata, label="test", frame=42)

    assert snap.frame == 42
    assert snap.state == StateReader(memory.read, symbols, gamedata).read()
    regions = {r.symbol: r for r in snap.regions}
    name = regions["wPlayerName"]
    assert name.address == symbols.addr("wPlayerName")
    assert bytes.fromhex(name.hex)[:7] == bytes(encode("YELLOW"))
    assert [f.path for f in name.fields] == ["player_name"]
    assert regions["wPlayerMoney"].hex == "003000"

    mons = regions["wPartyMons"]
    assert len(bytes.fromhex(mons.hex)) == 44  # one party member
    paths = {f.path: f for f in mons.fields}
    assert paths["party[0].species"].offset == 0x00
    assert paths["party[0].level"].offset == 0x21
    assert paths["party[0].hp"].length == 2


def test_every_field_stays_inside_its_region(memory, symbols, gamedata):
    _write_pikachu(memory, symbols)
    snap = export_snapshot(memory.read, symbols, gamedata, label="t", frame=0)
    for region in snap.regions:
        size = len(bytes.fromhex(region.hex))
        for f in region.fields:
            assert 0 <= f.offset and f.offset + f.length <= size, (region.symbol, f.path)
