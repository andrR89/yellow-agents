"""Screen reading from wTileMap: what text/menu is on screen, without a screenshot."""

from yellow_agent.state import SCREEN_COLS, SCREEN_ROWS, ScreenKind, StateReader, read_screen
from yellow_agent.text import encode

BOX_TL, BOX_H, BOX_TR, BOX_V, BOX_BL, BOX_BR = 0x79, 0x7A, 0x7B, 0x7C, 0x7D, 0x7E
SPACE, CURSOR, ARROW = 0x7F, 0xED, 0xEE
MAP_TILE = 0x01  # any overworld background tile id


def _blank(fill: int = MAP_TILE) -> list[int]:
    return [fill] * (SCREEN_COLS * SCREEN_ROWS)


def _put(tiles: list[int], col: int, row: int, values: list[int]) -> None:
    start = row * SCREEN_COLS + col
    tiles[start : start + len(values)] = values


def _text(s: str) -> list[int]:
    return encode(s)[:-1]  # drop terminator


def _box(tiles: list[int], col: int, row: int, width: int, height: int) -> None:
    _put(tiles, col, row, [BOX_TL] + [BOX_H] * (width - 2) + [BOX_TR])
    for r in range(row + 1, row + height - 1):
        _put(tiles, col, r, [BOX_V] + [SPACE] * (width - 2) + [BOX_V])
    _put(tiles, col, row + height - 1, [BOX_BL] + [BOX_H] * (width - 2) + [BOX_BR])


def _dialog(line1: str, line2: str, arrow: bool) -> list[int]:
    tiles = _blank()
    _box(tiles, 0, 12, 20, 6)
    _put(tiles, 1, 14, _text(line1))
    _put(tiles, 1, 16, _text(line2))
    if arrow:
        _put(tiles, 18, 16, [ARROW])
    return tiles


def test_overworld_has_no_text():
    screen = read_screen(_blank(), font_loaded=False, player_loaded=True)
    assert screen.kind is ScreenKind.OVERWORLD
    assert screen.lines == []
    assert screen.cursor is None


def test_no_player_sprite_and_no_box_is_a_cutscene():
    # Title screen and Oak's intro: the map id is already set but nothing is controllable.
    screen = read_screen(_blank(), font_loaded=False, player_loaded=False)
    assert screen.kind is ScreenKind.CUTSCENE


def test_dialog_lines_are_decoded_and_arrow_is_dropped():
    for arrow in (True, False):  # the ▼ blinks: both frames must read the same
        screen = read_screen(
            _dialog("YELLOW is", "playing the SNES!", arrow), font_loaded=True, player_loaded=True
        )
        assert screen.kind is ScreenKind.TEXT
        assert screen.lines == ["YELLOW is", "playing the SNES!"]


def test_box_without_font_flag_still_counts_as_text():
    # The intro and title screens draw boxes without setting wFontLoaded.
    screen = read_screen(
        _dialog("Hello there!", "", arrow=False), font_loaded=False, player_loaded=False
    )
    assert screen.kind is ScreenKind.TEXT


def test_menu_cursor_names_the_selected_item():
    tiles = _blank()
    _box(tiles, 10, 0, 10, 8)
    _put(tiles, 11, 2, [CURSOR] + _text("POKéMON"))
    _put(tiles, 12, 4, _text("ITEM"))
    _put(tiles, 12, 6, _text("EXIT"))
    screen = read_screen(tiles, font_loaded=True, player_loaded=True)
    assert screen.kind is ScreenKind.MENU
    assert screen.cursor == "POKéMON"
    assert screen.lines == ["POKéMON", "ITEM", "EXIT"]


def test_side_by_side_boxes_are_split():
    tiles = _dialog("Is it OK?", "", arrow=False)
    _box(tiles, 0, 0, 8, 5)
    _box(tiles, 10, 0, 8, 5)
    _put(tiles, 1, 2, [CURSOR] + _text("YES"))
    _put(tiles, 12, 2, _text("NO"))
    screen = read_screen(tiles, font_loaded=True, player_loaded=True)
    assert screen.cursor == "YES"
    assert screen.lines == ["YES | NO", "Is it OK?"]


def test_reader_includes_screen_and_sprite_facing(memory, symbols, gamedata):
    memory.poke(symbols.addr("wTileMap"), _dialog("Hi!", "", arrow=True))
    memory.poke(symbols.addr("wFontLoaded"), [1])
    memory.poke(symbols.addr("wSpritePlayerStateData1PictureID"), [1])
    memory.poke(symbols.addr("wSpritePlayerStateData1FacingDirection"), [0x0C])
    state = StateReader(memory.read, symbols, gamedata).read()
    assert state.screen.kind is ScreenKind.TEXT
    assert state.screen.lines == ["Hi!"]
    assert state.facing == "right"


def test_battle_hp_bar_tiles_are_not_text():
    tiles = _blank(fill=0x7F)
    _put(tiles, 1, 0, _text("PIKACHU"))
    _put(tiles, 4, 1, [0x6E, 0xFB])  # <LV>5
    _put(tiles, 1, 2, [0x73, 0x71, 0x62] + [0x6B] * 6 + [0x6C])  # HP: + bar
    _put(tiles, 1, 3, [0x74] + [0x76] * 8 + [0x78])  # box underline
    _box(tiles, 8, 12, 12, 6)
    _put(tiles, 9, 16, [CURSOR] + _text("ITEM  RUN"))
    screen = read_screen(tiles, font_loaded=True, player_loaded=True)
    assert screen.lines == ["PIKACHU", "Lv5", "ITEM RUN"]
    assert screen.cursor == "ITEM"
