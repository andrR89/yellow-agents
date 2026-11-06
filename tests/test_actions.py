"""High-level actions. No ROM: pure helpers first, then actions on a scripted FakeGame."""

from __future__ import annotations

import pytest

from tests.fake_game import FakeGame, Phase, menu, overworld, text
from yellow_agent.actions import (
    BATTLE_STABLE_FRAMES,
    QUIET_FRAMES,
    STABLE_FRAMES,
    ActionError,
    StopReason,
    advance_text,
    choose,
    cursor_moves,
    is_battle_menu,
    press_buttons,
    talk,
    text_ready,
    use_move,
    validate_slot,
    validate_walk,
    wait,
    walk,
)
from yellow_agent.emulator import StepResult
from yellow_agent.state import Screen, ScreenKind
from yellow_agent.text import MORE_TEXT

BLANK = [0x7F] * 360  # 20x18 tiles of spaces


# -- text_ready ---------------------------------------------------------------------


def _tiles_with_arrow() -> list[int]:
    tiles = list(BLANK)
    tiles[16 * 20 + 18] = MORE_TEXT  # ▼ at the text box's bottom-right
    return tiles


def test_text_is_ready_when_the_arrow_shows():
    assert text_ready(_tiles_with_arrow(), stable_frames=0)


def test_text_still_printing_is_not_ready():
    assert not text_ready(BLANK, stable_frames=3)


def test_text_without_arrow_is_ready_once_the_screen_stops_changing():
    assert text_ready(BLANK, stable_frames=STABLE_FRAMES)


def test_arrow_outside_the_text_box_does_not_count():
    tiles = list(BLANK)
    tiles[2 * 20 + 18] = MORE_TEXT
    assert not text_ready(tiles, stable_frames=0)


# -- menus --------------------------------------------------------------------------

YES_NO = Screen(
    kind=ScreenKind.MENU, lines=["YES", "NO", "give a nickname", "to PIKACHU?"], cursor="YES"
)
BATTLE = Screen(
    kind=ScreenKind.MENU,
    lines=["EEVEE", "Lv5", "PIKACHU", "Lv5", "FIGHT PKMN", "ITEM RUN"],
    cursor="FIGHT",
)


def test_cursor_moves_down_a_list():
    assert cursor_moves(YES_NO, "no") == ["down"]
    assert cursor_moves(YES_NO, "YES") == []


def test_cursor_moves_on_the_battle_grid():
    assert cursor_moves(BATTLE, "RUN") == ["down", "right"]
    assert cursor_moves(BATTLE.model_copy(update={"cursor": "RUN"}), "FIGHT") == ["up", "left"]


def test_cursor_moves_reject_items_not_on_screen():
    with pytest.raises(ActionError, match="not on screen"):
        cursor_moves(YES_NO, "MAYBE")


def test_cursor_moves_need_a_cursor():
    with pytest.raises(ActionError, match="no menu cursor"):
        cursor_moves(Screen(kind=ScreenKind.TEXT, lines=["Hi"]), "YES")


def test_battle_menu_needs_fight_and_a_battle():
    assert is_battle_menu(BATTLE, in_battle=True)
    assert not is_battle_menu(BATTLE, in_battle=False)
    assert not is_battle_menu(YES_NO, in_battle=True)


# -- advance_text / talk ------------------------------------------------------------


def test_advance_text_presses_once_per_box_and_stops_at_the_choice():
    game = FakeGame(
        [
            text("OAK: Hey!"),
            text("Wild POKéMON live", "in tall grass!"),
            menu("YES", "NO", cursor="YES"),
        ]
    )
    r = advance_text(game)
    assert r.stop is StopReason.MENU
    assert game.pressed == ["a", "a"]
    assert r.transcript == ["OAK: Hey!", "Wild POKéMON live", "in tall grass!", "YES", "NO"]


def test_advance_text_waits_through_a_script_between_boxes():
    game = FakeGame(
        [
            text("OAK: Come with me!"),
            overworld(frames=200, input_enabled=False),
            text("OAK: Here we are."),
            overworld(),
        ]
    )
    r = advance_text(game)
    assert r.stop is StopReason.OVERWORLD
    assert game.pressed == ["a", "a"]
    assert r.frames >= 200 + QUIET_FRAMES


def test_text_without_arrow_is_pressed_once_it_stays_still():
    game = FakeGame([text("PIKACHU used", "THUNDERSHOCK!", arrow=False), overworld()])
    r = advance_text(game)
    assert game.pressed == ["a"] and r.stop is StopReason.OVERWORLD
    assert r.frames >= STABLE_FRAMES + QUIET_FRAMES


def test_advance_text_on_free_overworld_waits_for_a_scene_then_stops():
    r = advance_text(FakeGame([overworld()]))
    assert (r.stop, r.presses) == (StopReason.OVERWORLD, 0)
    assert QUIET_FRAMES <= r.frames <= QUIET_FRAMES + 2


def test_advance_text_catches_a_battle_that_starts_after_a_long_pause():
    # Rival in Oak's lab: ~213 quiet frames, then wIsInBattle, then the battle text.
    game = FakeGame(
        [
            overworld(frames=60),
            text("GEMINI wants", "to fight!"),
            menu("EEVEE", "FIGHT PKMN", "ITEM RUN", cursor="FIGHT"),
        ],
        in_battle=True,
    )
    assert advance_text(game).stop is StopReason.BATTLE_MENU


def test_advance_text_stops_at_the_frame_cap():
    r = advance_text(FakeGame([overworld(input_enabled=False)]), max_frames=100)
    assert r.stop is StopReason.LIMIT and r.frames == 100


def test_advance_text_reports_the_battle_menu():
    game = FakeGame(
        [
            text("GEMINI wants", "to fight!"),
            menu("EEVEE", "FIGHT PKMN", "ITEM RUN", cursor="FIGHT"),
        ],
        in_battle=True,
    )
    assert advance_text(game).stop is StopReason.BATTLE_MENU


def test_talk_reads_what_the_npc_says():
    game = FakeGame([overworld(frames=5), text("MOM: Right.", "All boys leave home"), overworld()])
    r = talk(game)
    assert game.pressed[0] == "a" and r.stop is StopReason.OVERWORLD
    assert r.transcript == ["MOM: Right.", "All boys leave home"]


def test_talk_to_nobody_stops_quickly():
    r = talk(FakeGame([overworld()]))
    assert (r.stop, r.presses, r.transcript) == (StopReason.OVERWORLD, 1, [])
    assert r.frames <= 24 + STABLE_FRAMES


def test_talk_needs_the_overworld():
    game = FakeGame([text("Hi")])
    with pytest.raises(ActionError, match="overworld"):
        talk(game)
    assert game.pressed == []


# -- walk ---------------------------------------------------------------------------

M, B, W = StepResult.MOVED, StepResult.BLOCKED, StepResult.WARPED


def test_walk_stops_when_blocked():
    game = FakeGame([overworld()], steps=[M, M, B])
    r = walk(game, "left", 5)
    assert (r.stop, r.tiles, game.pressed) == (StopReason.BLOCKED, 2, ["left"] * 3)


def test_walk_all_the_way():
    r = walk(FakeGame([overworld()], steps=[M, M, M]), "up", 3)
    assert (r.stop, r.tiles) == (StopReason.DONE, 3)


def test_walk_stops_at_a_warp():
    r = walk(FakeGame([overworld()], steps=[M, W, M]), "down", 3)
    assert (r.stop, r.tiles) == (StopReason.WARPED, 2)


def test_walk_stops_when_a_text_box_opens():
    game = FakeGame([overworld(frames=17), text("Hey! Wait!")], steps=[M, M])
    assert walk(game, "up", 2).stop is StopReason.TEXT


def test_walk_stops_when_a_script_takes_over():
    game = FakeGame([overworld(frames=17), overworld(input_enabled=False)], steps=[M, M])
    r = walk(game, "up", 2)
    assert (r.stop, r.tiles) == (StopReason.SCRIPT, 1)


@pytest.mark.parametrize("direction, tiles", [("jump", 1), ("up", 0), ("up", 21)])
def test_walk_validates_input(direction, tiles):
    with pytest.raises(ActionError):
        validate_walk(direction, tiles)


def test_walk_needs_the_overworld():
    game = FakeGame([text("Hi")])
    with pytest.raises(ActionError, match="advance_text"):
        walk(game, "up", 1)
    assert game.pressed == []


# -- choose / use_move ----------------------------------------------------------------


def test_choose_needs_a_menu():
    game = FakeGame([overworld()])
    with pytest.raises(ActionError, match="menu"):
        choose(game, "YES")
    assert game.pressed == []


def test_choose_rejects_items_not_on_screen():
    game = FakeGame([menu("YES", "NO", cursor="YES")])
    with pytest.raises(ActionError, match="not on screen"):
        choose(game, "MAYBE")
    assert game.pressed == []


def test_choose_the_item_under_the_cursor_presses_a_only():
    game = FakeGame([menu("YES", "NO", cursor="YES"), text("OK!"), overworld()])
    r = choose(game, "yes")
    assert game.pressed[0] == "a" and r.action == {"tool": "choose", "item": "yes"}
    assert r.stop is StopReason.OVERWORLD


@pytest.mark.parametrize("slot", [0, 5])
def test_use_move_validates_the_slot_range(slot):
    with pytest.raises(ActionError, match="slot"):
        validate_slot(slot)


def test_use_move_needs_the_battle_menu():
    game = FakeGame([menu("YES", "NO", cursor="YES")], in_battle=True)
    with pytest.raises(ActionError, match="battle menu"):
        use_move(game, 1)


def test_use_move_rejects_empty_slots_and_moves_without_pp():
    game = FakeGame([menu("EEVEE", "FIGHT PKMN", "ITEM RUN", cursor="FIGHT")], in_battle=True)
    with pytest.raises(ActionError, match="no move in slot 3"):
        use_move(game, 3)
    with pytest.raises(ActionError, match="GROWL has no PP"):
        use_move(game, 2)
    assert game.pressed == []


def test_walk_notices_a_script_that_starts_just_after_the_last_step():
    # Oak's trigger in the grass locks input 1 frame after the step ends (measured on the ROM).
    game = FakeGame([overworld(frames=18), overworld(input_enabled=False)], steps=[M])
    r = walk(game, "up", 1)
    assert (r.stop, r.tiles) == (StopReason.SCRIPT, 1)


def test_a_step_ignored_by_a_script_is_not_a_wall():
    game = FakeGame([overworld(frames=17), overworld(input_enabled=False)], steps=[M, B])
    game.phases[0].frames = 30  # locks between the two steps
    r = walk(game, "up", 2)
    assert r.stop is StopReason.SCRIPT


def test_a_short_pause_with_input_enabled_is_not_free_control():
    # After Oak's catch the game leaves input enabled for ~32 frames before he speaks again.
    game = FakeGame(
        [text("PIKACHU was caught!"), overworld(frames=40), text("OAK: Whew..."), overworld()]
    )
    r = advance_text(game)
    assert r.transcript == ["PIKACHU was caught!", "OAK: Whew..."]


def test_choose_on_the_battle_grid_compares_places_not_text():
    grid = menu("EEVEE", "FIGHT PKMN", "ITEM RUN", cursor="FIGHT PKMN")
    game = FakeGame([grid, text("OK"), overworld()], in_battle=True)
    choose(game, "FIGHT")
    assert game.pressed[0] == "a"


def test_choose_presses_a_again_when_the_menu_ignored_it():
    # Session 4: the A on THUNDERSHOCK landed while the move list was drawing and was dropped.
    moves = menu("THUNDERSHOCK", "GROWL", "-", cursor="THUNDERSHOCK")
    moves.ignore_a = 1
    game = FakeGame([moves, text("PIKACHU used", "THUNDERSHOCK!"), overworld()])
    r = choose(game, "THUNDERSHOCK")
    assert game.pressed[:2] == ["a", "a"] and r.stop is StopReason.OVERWORLD


def test_battle_text_without_arrow_waits_longer_before_a():
    assert not text_ready(BLANK, stable_frames=STABLE_FRAMES * 3, in_battle=True)
    assert text_ready(BLANK, stable_frames=BATTLE_STABLE_FRAMES, in_battle=True)  # level up
    assert text_ready(_tiles_with_arrow(), stable_frames=0, in_battle=True)


def test_transcript_keeps_battle_text_that_moves_on_by_itself():
    game = FakeGame(
        [
            Phase(Screen(kind=ScreenKind.TEXT, lines=["EEVEE used", "TACKLE!"]), frames=40),
            menu("EEVEE", "FIGHT PKMN", "ITEM RUN", cursor="FIGHT"),
        ],
        in_battle=True,
    )
    r = advance_text(game)
    assert r.stop is StopReason.BATTLE_MENU and game.pressed == []
    assert r.transcript[:2] == ["EEVEE used", "TACKLE!"]


def test_press_buttons_reports_where_it_ended():
    game = FakeGame([text("Hi"), overworld()])
    r = press_buttons(game, ["a"])
    assert (r.stop, r.presses, game.pressed) == (StopReason.OVERWORLD, 1, ["a"])


@pytest.mark.parametrize("buttons", [[], ["jump"], ["a"] * 31])
def test_press_buttons_validates(buttons):
    with pytest.raises(ActionError):
        press_buttons(FakeGame([overworld()]), buttons)


def test_wait_runs_frames_and_validates():
    game = FakeGame([overworld(frames=10, input_enabled=False), text("Hey!")])
    r = wait(game, 30)
    assert (r.stop, r.frames) == (StopReason.TEXT, 30)
    with pytest.raises(ActionError):
        wait(game, 601)


def test_use_move_also_works_from_the_move_list():
    # qwen3:14b chose FIGHT itself, then called use_move on the move list (session 8).
    moves = menu("THUNDERSHOCK", "GROWL", "-", cursor="THUNDERSHOCK")
    main = menu("EEVEE", "FIGHT PKMN", "ITEM RUN", cursor="FIGHT")
    game = FakeGame([moves, text("PIKACHU used", "THUNDERSHOCK!"), main], in_battle=True)
    r = use_move(game, 1)
    assert game.pressed[0] == "a" and r.stop is StopReason.BATTLE_MENU
