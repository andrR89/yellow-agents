"""Eval scenarios: a start built by code (no save files), a goal for the prompt, a judge.

Every setup is scripted with the high-level actions, so each model starts from the same
emulator state. Goals include a short guide (where the stairs, doors and exits are): there is
no map or pathfinding until Phase 3, and the point here is decisions, not exploration.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from .action_route import play_to_pikachu_with_actions
from .actions import StopReason, advance_text, use_move, walk
from .newgame import new_game
from .state import ScreenKind

if TYPE_CHECKING:
    from .emulator import Emulator

Verdict = Literal["success", "failure"] | None
Judge = Callable[["Emulator"], Verdict]
RIVAL = "GEMINI"


def _got_pikachu() -> Judge:
    def judge(emu: Emulator) -> Verdict:
        s = emu.state()
        pikachu = any(m.species == "PIKACHU" for m in s.party)
        return "success" if pikachu and s.screen.kind is ScreenKind.OVERWORLD else None

    return judge


def _won_battle() -> Judge:
    """Success when a battle the agent was in ends with wBattleResult == 0 (won)."""
    seen = False

    def judge(emu: Emulator) -> Verdict:
        nonlocal seen
        if emu.in_battle():
            seen = True
            return None
        if seen:
            return "success" if emu.battle_result() == 0 else "failure"
        return None

    return judge


def _reached(map_name: str) -> Callable[[], Judge]:
    def factory() -> Judge:
        return lambda emu: "success" if emu.state().map_name == map_name else None

    return factory


def _setup_new_game(emu: Emulator, player: str) -> None:
    new_game(emu, player, RIVAL)


def _setup_lab_with_pikachu(emu: Emulator, player: str) -> None:
    play_to_pikachu_with_actions(emu, player, RIVAL)


def _setup_after_rival(emu: Emulator, player: str) -> None:
    """Pikachu in hand, then the rival's battle played with THUNDERSHOCK every turn (won or
    lost, the story goes on), until the player has control in the lab again."""
    _setup_lab_with_pikachu(emu, player)
    walk(emu, "down", 8)  # the rival stops you on the way out
    fought = False
    for _ in range(30):
        if emu.in_battle() and emu.state().screen.kind is ScreenKind.MENU:
            r = use_move(emu, 1)
        else:
            r = advance_text(emu)  # also waits out the rival walking up (~300 quiet frames)
        fought = fought or emu.in_battle() or r.state.battle.kind != "none"
        if fought and r.stop is StopReason.OVERWORLD and not emu.in_battle():
            return
    raise RuntimeError("scripted rival battle did not end")


@dataclass(frozen=True)
class Scenario:
    name: str
    goal: str
    max_turns: int
    setup: Callable[[Emulator, str], None]  # (emulator, player name)
    judge: Callable[[], Judge]  # a fresh judge per run (some keep state)


SCENARIOS: dict[str, Scenario] = {
    s.name: s
    for s in [
        Scenario(
            name="rival_battle",
            goal=(
                "You are in Professor Oak's lab with your PIKACHU, free to move. Walk south "
                "towards the lab's exit: your rival GEMINI will stop you and challenge you to "
                "a battle. Win the battle. PIKACHU's attacking move is THUNDERSHOCK."
            ),
            max_turns=25,
            setup=_setup_lab_with_pikachu,
            judge=_won_battle,
        ),
        Scenario(
            name="pikachu",
            goal=(
                "A new game: you are in your bedroom, on the 2nd floor of your house in Pallet "
                "Town. The stairs are at the top right of the bedroom (x=7, y=1). Downstairs, "
                "the front door is the mat at the bottom of the room (x=3, y=7): stand on it and "
                "walk down to go outside. In Pallet Town, walk "
                "north to the top edge of town (x=10-11, y=0) and into the tall grass: "
                "Professor Oak stops you and takes you to his lab; let the scene play. When you "
                "can move in the lab, take the Poké Ball on the table to your right: stand right "
                "below it and talk to it facing up. Decline to give a nickname. Done when "
                "PIKACHU is in your party and you can move again."
            ),
            max_turns=40,
            setup=_setup_new_game,
            judge=_got_pikachu,
        ),
        Scenario(
            name="route1",
            goal=(
                "You are in Professor Oak's lab after your first battle with GEMINI. Leave the "
                "lab: the exit is at the bottom of the room (x=4, y=11). Outside, the lab blocks "
                "the way north: walk left to x=9, north to y=2, right to x=10, then north onto "
                "ROUTE_1. Done when you are on ROUTE_1."
            ),
            max_turns=40,
            setup=_setup_after_rival,
            judge=_reached("ROUTE_1"),
        ),
    ]
}
