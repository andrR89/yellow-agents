import pytest

from yellow_agent.newgame import cursor_position, keyboard_position, validate_name
from yellow_agent.state import SCREEN_COLS, SCREEN_ROWS
from yellow_agent.text import CURSOR


def test_keyboard_positions_match_the_screen():
    # measured on the real naming screen: ▶ at (5, 1) for A, letters 2 tiles apart
    assert keyboard_position("A") == (5, 1)
    assert keyboard_position("I") == (5, 17)
    assert keyboard_position("J") == (7, 1)
    assert keyboard_position("Z") == (9, 15)


def test_cursor_position():
    tiles = [0x7F] * (SCREEN_COLS * SCREEN_ROWS)
    assert cursor_position(tiles) is None
    tiles[7 * SCREEN_COLS + 3] = CURSOR
    assert cursor_position(tiles) == (7, 3)


@pytest.mark.parametrize("name", ["CLAUDE", "GEMINI", "A", "ABCDEFG"])
def test_valid_names(name):
    assert validate_name(name) == name


@pytest.mark.parametrize("name", ["", "ABCDEFGH", "claude", "GPT-5", "R2D2", "A B"])
def test_invalid_names(name):
    with pytest.raises(ValueError):
        validate_name(name)
