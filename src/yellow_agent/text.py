"""Decoding of the Gen 1 (English) character set used in names and text buffers.

Source of truth: pret/pokeyellow constants/charmap.asm.
"""

from __future__ import annotations

from collections.abc import Iterable

TERMINATOR = 0x50

_CHARMAP: dict[int, str] = {
    0x7F: " ",
    0x71: "’",
    0xBA: "é",
    0xE3: "-",
    0xE6: "?",
    0xE7: "!",
    0xE8: ".",
    0xEF: "♂",
    0xF1: "×",
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
    reverse = {v: k for k, v in _CHARMAP.items() if len(v) == 1}
    try:
        return [reverse[ch] for ch in text] + [TERMINATOR]
    except KeyError as exc:
        raise ValueError(f"character not encodable in Gen 1 charset: {exc.args[0]!r}") from exc
