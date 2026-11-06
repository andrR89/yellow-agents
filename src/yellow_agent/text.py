"""Decoding of the Gen 1 (English) character set used in names and text buffers.

Source of truth: pret/pokeyellow constants/charmap.asm.
"""

from __future__ import annotations

from collections.abc import Iterable

TERMINATOR = 0x50

_CHARMAP: dict[int, str] = {
    0x7F: " ",
    0x71: "’",
    0x75: "…",
    0xE0: "'",
    0xBA: "é",
    0xE3: "-",
    0xE6: "?",
    0xE7: "!",
    0xE8: ".",
    0xEF: "♂",
    0xF0: "¥",
    0xF1: "×",
    0xF2: ".",  # decimal point
    0xF3: "/",
    0xF4: ",",
    0xF5: "♀",
    0xE1: "PK",
    0xE2: "MN",
    0xBB: "'d",
    0xBC: "'l",
    0xBD: "'s",
    0xBE: "'t",
    0xBF: "'v",
    0xE4: "'r",
    0xE5: "'m",
    0x9A: "(",
    0x9B: ")",
    0x9C: ":",
    0x9D: ";",
    0x9E: "[",
    0x9F: "]",
}
_CHARMAP.update({0x80 + i: chr(ord("A") + i) for i in range(26)})
_CHARMAP.update({0xA0 + i: chr(ord("a") + i) for i in range(26)})
_CHARMAP.update({0xF6 + i: str(i) for i in range(10)})


# Tiles that only matter on screen (wTileMap), never inside names.
BOX_TILES = frozenset(range(0x79, 0x7F))  # ┌ ─ ┐ │ └ ┘
CURSOR = 0xED  # ▶ selected menu item
CURSOR_IDLE = 0xEC  # ▷ menu item selected earlier (e.g. swap source)
MORE_TEXT = 0xEE  # ▼ blinking "press A" arrow


def decode(data: Iterable[int], unknown: str = "?") -> str:
    """Decode bytes until the 0x50 terminator."""
    out: list[str] = []
    for byte in data:
        if byte == TERMINATOR:
            break
        out.append(_CHARMAP.get(byte, unknown))
    return "".join(out)


def encode(text: str) -> list[int]:
    """Encode simple text (letters, digits, space, basic punctuation) + terminator.

    Useful for tests and for writing names into RAM in eval scenarios.
    """
    reverse: dict[str, int] = {}
    for k, v in _CHARMAP.items():  # first code wins: "." is 0xE8, not the decimal point
        if len(v) == 1:
            reverse.setdefault(v, k)
    try:
        return [reverse[ch] for ch in text] + [TERMINATOR]
    except KeyError as exc:
        raise ValueError(f"character not encodable in Gen 1 charset: {exc.args[0]!r}") from exc


# On screen, 0x60-0x78 are mostly HP bar / status box graphics in battle, not text.
_SCREEN_GLYPHS: dict[int, str | None] = {b: None for b in range(0x60, 0x79)}
_SCREEN_GLYPHS.update({0x6E: "Lv", 0x75: "…"})


def glyph(byte: int) -> str | None:
    """Printable text for one wTileMap tile, or None if the tile is not a character."""
    if byte in _SCREEN_GLYPHS:
        return _SCREEN_GLYPHS[byte]
    return _CHARMAP.get(byte)
