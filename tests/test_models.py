"""Model layer without network: request building and response parsing."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from yellow_agent.models import load_model
from yellow_agent.models.base import ToolSpec
from yellow_agent.models.openai_compat import build_request, parse_response


def _resp(content="", tool_calls=None, usage=None):
    msg = NS(content=content, tool_calls=tool_calls)
    return NS(choices=[NS(message=msg)], usage=usage)


def test_parse_reads_tool_calls_tokens_and_openrouter_cost():
    call = NS(id="c1", function=NS(name="walk", arguments='{"direction": "up", "tiles": 2}'))
    usage = NS(prompt_tokens=1200, completion_tokens=40, cost=0.00014)
    r = parse_response(_resp("going up", [call], usage), "openrouter:x", 0.5)
    assert r.text == "going up" and r.latency_s == 0.5
    assert [(c.name, c.arguments) for c in r.tool_calls] == [
        ("walk", {"direction": "up", "tiles": 2})
    ]
    assert (r.usage.input_tokens, r.usage.output_tokens, r.cost_usd) == (1200, 40, 0.00014)


def test_parse_without_cost_is_free_and_bad_json_is_kept():
    call = NS(id=None, function=NS(name="walk", arguments="{not json"))
    r = parse_response(_resp(None, [call], NS(prompt_tokens=1, completion_tokens=2)), "ollama:q", 0)
    assert r.cost_usd == 0.0 and r.text == ""
    assert r.tool_calls[0].arguments == {"_raw": "{not json"}


def test_request_asks_for_cost_and_a_tool_call():
    tools = [
        ToolSpec(name="talk", description="Talk.", parameters={"type": "object", "properties": {}})
    ]
    req = build_request("m", "sys", [], tools, 256, provider="openrouter")
    assert req["extra_body"] == {"usage": {"include": True}}
    assert req["tool_choice"] == "required" and req["temperature"] == 0
    assert req["messages"][0] == {"role": "system", "content": "sys"}


def test_ollama_request_turns_thinking_off():
    req = build_request("qwen3:4b", "sys", [], None, 256, provider="ollama")
    assert req["reasoning_effort"] == "none" and "extra_body" not in req
    assert "tool_choice" not in req


def test_openrouter_needs_its_key(monkeypatch):
    pytest.importorskip("openai")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        load_model("openrouter:anthropic/claude-haiku-5.5")


def test_request_without_forcing_a_tool():
    tools = [ToolSpec(name="talk", description="Talk.", parameters={"type": "object"})]
    req = build_request("m", "sys", [], tools, 256, provider="openrouter", force_tool=False)
    assert "tool_choice" not in req and req["tools"]


def test_ollama_native_request_turns_thinking_off_and_keeps_the_context_small():
    from yellow_agent.models.ollama import NUM_CTX, build_chat

    tools = [ToolSpec(name="talk", description="Talk.", parameters={"type": "object"})]
    body = build_chat("qwen3:4b", "sys", [], tools, 300)
    assert body["think"] is False and body["stream"] is False
    assert body["options"]["num_ctx"] == NUM_CTX == 4096 and body["options"]["num_predict"] == 300
    assert body["tools"][0]["function"]["name"] == "talk"


def test_ollama_native_response_parsing():
    from yellow_agent.models.ollama import parse_chat

    data = {"message": {"content": "", "tool_calls": [
        {"function": {"name": "walk", "arguments": {"direction": "up", "tiles": 2}}}]},
        "prompt_eval_count": 600, "eval_count": 25}  # fmt: skip
    r = parse_chat(data, "ollama:q", 1.5)
    assert [(c.name, c.arguments) for c in r.tool_calls] == [
        ("walk", {"direction": "up", "tiles": 2})
    ]
    assert (r.usage.input_tokens, r.usage.output_tokens, r.cost_usd) == (600, 25, 0.0)
