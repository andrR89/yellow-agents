import pytest

from yellow_agent.symbols import SymbolTable
from yellow_agent.text import decode, encode


def test_parse_symbols(symbols):
    assert symbols.addr("wCurMap") == 0xD35D
    assert "wPartyMons" in symbols
    assert len(symbols) == 20


def test_missing_symbol_has_helpful_error(symbols):
    with pytest.raises(KeyError, match="wNope"):
        symbols.addr("wNope")


def test_parser_tolerates_junk():
    table = SymbolTable.parse("; comment\n\ngarbage line\n00:c000 wFoo ; trailing\n")
    assert table.addr("wFoo") == 0xC000


def test_decode_stops_at_terminator():
    assert decode([0x80 + 0, 0xA0 + 18, 0xA0 + 7, 0x50, 0x80]) == "Ash"


def test_roundtrip_with_digits_and_space():
    assert decode(encode("RED 42")) == "RED 42"


def test_encode_rejects_unknown_chars():
    with pytest.raises(ValueError):
        encode("ç")
