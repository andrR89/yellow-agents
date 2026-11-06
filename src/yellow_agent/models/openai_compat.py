"""OpenAI Chat Completions API: OpenAI itself, OpenRouter and Ollama's compatible endpoint.

Request building and response parsing are plain functions, so they are tested without the
`openai` package or the network.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from .base import Message, ModelResponse, ToolCall, ToolSpec, Usage

OLLAMA_BASE_URL = "http://localhost:11434/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def build_request(
    model: str,
    system: str,
    messages: list[Message],
    tools: list[ToolSpec] | None,
    max_tokens: int,
    *,
    provider: str,
) -> dict[str, Any]:
    req: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0,  # benchmarks: as repeatable as the provider allows
        "messages": [{"role": "system", "content": system}]
        + [{"role": m.role, "content": m.content} for m in messages],
    }
    if tools:
        req["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]
        if provider != "ollama":  # Ollama's compatible endpoint ignores it
            req["tool_choice"] = "required"
    if provider == "openrouter":
        req["extra_body"] = {"usage": {"include": True}}  # real cost per call, in USD
    elif provider == "ollama":
        # qwen3 thinks by default and then often answers with no tool call. Ollama 0.40 ignores
        # extra_body={"think": False} on this endpoint, and "/no_think" in the prompt stops tool
        # calls; reasoning_effort="none" keeps them (measured, session 5).
        req["reasoning_effort"] = "none"
    return req


def parse_response(resp: Any, name: str, latency_s: float) -> ModelResponse:
    msg = resp.choices[0].message
    calls: list[ToolCall] = []
    for tc in msg.tool_calls or []:
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {"_raw": tc.function.arguments}  # surfaced to the agent as an error
        calls.append(ToolCall(name=tc.function.name, arguments=args, id=tc.id))
    usage = resp.usage
    tokens = Usage(usage.prompt_tokens, usage.completion_tokens) if usage else Usage()
    cost = float(getattr(usage, "cost", None) or 0.0) if usage else 0.0
    return ModelResponse(
        text=msg.content or "",
        tool_calls=calls,
        usage=tokens,
        model=name,
        latency_s=latency_s,
        cost_usd=cost,
    )


class OpenAICompatModel:
    """Needs `pip install .[openai]`. OpenAI: OPENAI_API_KEY; OpenRouter: OPENROUTER_API_KEY;
    Ollama: nothing."""

    def __init__(self, model: str, base_url: str | None = None, provider: str = "openai"):
        import openai  # optional dependency

        self.name = f"{provider}:{model}"
        self._model = model
        self._provider = provider
        if provider == "ollama":
            api_key: str | None = "ollama"  # Ollama ignores the key
        elif provider == "openrouter":
            api_key = os.environ.get("OPENROUTER_API_KEY")
            if not api_key:
                raise ValueError("set OPENROUTER_API_KEY to use openrouter: models")
        else:
            api_key = None  # the SDK reads OPENAI_API_KEY
        self._client = openai.OpenAI(base_url=base_url, api_key=api_key, max_retries=3)

    def complete(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 1024,
    ) -> ModelResponse:
        req = build_request(
            self._model, system, messages, tools, max_tokens, provider=self._provider
        )
        start = time.perf_counter()
        resp = self._client.chat.completions.create(**req)
        return parse_response(resp, self.name, time.perf_counter() - start)
