"""The agent loop with a scripted model on the FakeGame: no ROM, no network."""

from __future__ import annotations

import json

import pytest

from tests.fake_game import FakeGame, menu, overworld, text
from yellow_agent.actions import ActionError
from yellow_agent.agent import TOOLS, build_prompt, execute, observe, run_agent
from yellow_agent.models.base import ModelResponse, ToolCall, Usage


class ScriptedModel:
    """Answers with the given tool calls in order (None = an answer with no tool call)."""

    name = "fake:scripted"

    def __init__(self, calls, cost=0.001, fail_first=0):
        self.calls = list(calls)
        self.prompts: list[str] = []
        self.cost = cost
        self.fail_first = fail_first

    def complete(self, system, messages, tools=None, max_tokens=1024):
        if self.fail_first:
            self.fail_first -= 1
            raise RuntimeError("502 from provider")
        self.prompts.append(messages[-1].content)
        call = self.calls.pop(0) if self.calls else None
        return ModelResponse(
            text="thinking",
            tool_calls=[call] if call else [],
            usage=Usage(100, 10),
            model=self.name,
            latency_s=0.2,
            cost_usd=self.cost,
        )


def T(name, **args):
    return ToolCall(name=name, arguments=args)


def on_overworld(game):
    return "success" if game.screen().kind.value == "overworld" else None


def test_the_loop_runs_until_the_judge_says_success():
    game = FakeGame([text("OAK: Hey!"), overworld()])
    model = ScriptedModel([T("advance_text")])
    run = run_agent(game, model, "get out", on_overworld, max_turns=5, budget_usd=1)
    assert (run.stop, run.turns, run.tools) == ("success", 1, {"advance_text": 1})
    assert run.cost_usd == pytest.approx(0.001) and run.input_tokens == 100


def test_invalid_calls_are_counted_and_shown_to_the_model_next_turn():
    game = FakeGame([text("Hi"), overworld()])
    model = ScriptedModel([T("walk", direction="up", tiles=2), T("advance_text")])
    run = run_agent(game, model, "g", on_overworld, max_turns=5, budget_usd=1)
    assert run.stop == "success" and run.invalid_actions == 1
    assert "ERROR: walk needs the overworld" in model.prompts[1]


def test_an_answer_without_a_tool_call_is_an_error_turn():
    game = FakeGame([text("Hi"), overworld()])
    model = ScriptedModel([None, T("advance_text")])
    run = run_agent(game, model, "g", on_overworld, max_turns=5, budget_usd=1)
    assert run.no_tool_calls == 1 and run.turns == 2
    assert "no tool was called" in model.prompts[1]


def test_the_budget_stops_the_run():
    game = FakeGame([text("a"), text("b"), text("c"), overworld()])
    model = ScriptedModel([T("advance_text")] * 3, cost=0.6)
    run = run_agent(game, model, "g", lambda g: None, max_turns=10, budget_usd=1.0)
    assert (run.stop, run.turns) == ("budget", 2)


def test_model_errors_are_retried_then_abandon_the_run(monkeypatch):
    monkeypatch.setattr("yellow_agent.agent.time.sleep", lambda s: None)
    game = FakeGame([overworld()])
    run = run_agent(game, ScriptedModel([], fail_first=5), "g", lambda g: None, max_turns=10,
                    budget_usd=1)  # fmt: skip
    assert (run.stop, run.model_errors) == ("model_error", 3)


def test_failure_from_the_judge_ends_the_run():
    game = FakeGame([text("You lost!"), overworld()])
    run = run_agent(game, ScriptedModel([T("advance_text")]), "g",
                    lambda g: "failure" if g.screen().kind.value == "overworld" else None,
                    max_turns=5, budget_usd=1)  # fmt: skip
    assert run.stop == "failure"


def test_execute_rejects_unknown_tools_and_bad_arguments():
    game = FakeGame([overworld()])
    with pytest.raises(ActionError, match="unknown tool"):
        execute(game, T("fly", to="Cerulean"))
    with pytest.raises(ActionError, match="tiles"):
        execute(game, T("walk", direction="up", tiles="many"))
    with pytest.raises(ActionError, match="not valid JSON"):
        execute(game, ToolCall(name="walk", arguments={"_raw": "{oops"}))
    assert game.pressed == []


def test_execute_accepts_numbers_as_strings():
    from yellow_agent.emulator import StepResult

    game = FakeGame([overworld()], steps=[StepResult.MOVED] * 2)
    r = execute(game, T("walk", direction="up", tiles="2"))
    assert r.tiles == 2


def test_prompt_has_goal_state_and_recent_actions():
    game = FakeGame([menu("YES", "NO", cursor="YES")])
    state = game.state()
    p = build_prompt("beat GEMINI", 3, 25, state, [])
    assert p.startswith("GOAL: beat GEMINI\nTURN 3 of 25")
    obs = json.loads(p.split("STATE: ", 1)[1].split("\n", 1)[0])
    assert obs == observe(state) and obs["screen"]["cursor"] == "YES"
    assert obs["party"][0]["moves"] == ["THUNDERSHOCK (30 PP)", "GROWL (0 PP)"]


def test_every_tool_has_a_json_schema_object():
    assert {t.name for t in TOOLS} == {
        "advance_text", "go_to", "walk", "talk", "choose", "use_move", "press_buttons", "wait",
    }  # fmt: skip
    assert all(t.parameters["type"] == "object" for t in TOOLS)


def test_reason_is_kept_as_what_the_model_said_and_not_passed_to_the_action():
    game = FakeGame([text("Hi"), overworld()])
    model = ScriptedModel([T("advance_text", reason="Read Oak's lines.")])
    run = run_agent(game, model, "g", on_overworld, max_turns=3, budget_usd=1)
    assert run.stop == "success" and run.invalid_actions == 0
    assert all("reason" in t.parameters["properties"] for t in TOOLS)


def test_three_identical_failures_in_a_row_get_a_warning():
    from yellow_agent.agent import HistoryItem, loop_warning

    bump = HistoryItem(1, {"tool": "walk", "direction": "down", "tiles": 1}, "stop=blocked")
    assert loop_warning([bump, bump]) is None
    assert "WARNING" in loop_warning([bump, bump, bump])
    moved = HistoryItem(4, {"tool": "walk", "direction": "left", "tiles": 1}, "stop=done")
    assert loop_warning([bump, bump, moved]) is None


def test_prompt_shows_the_map_exits_and_people():
    from yellow_agent.navigation import Exit, MapGrid, Person

    grid = MapGrid(width=8, height=8, walkable=[[True] * 8] * 8,
                   exits=[Exit(kind="warp", to="REDS_HOUSE_1F", x=7, y=1),
                          Exit(kind="edge", to="ROUTE_1", side="north")],
                   people=[Person(x=4, y=3, who="pikachu")])  # fmt: skip
    p = build_prompt("g", 1, 5, FakeGame([overworld()]).state(), [], grid)
    m = json.loads(p.split("MAP: ", 1)[1].split("\n", 1)[0])
    assert m["exits"] == [
        {"to": "REDS_HOUSE_1F", "x": 7, "y": 1},
        {"to": "ROUTE_1", "edge": "north"},
    ]
    assert m["people"] == [{"who": "pikachu", "x": 4, "y": 3}] and m["size"]["width"] == 8
