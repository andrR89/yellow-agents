from __future__ import annotations

import time

from .base import Message, ModelResponse, ToolCall, ToolSpec, Usage


class ClaudeModel:
    """Anthropic Messages API. Needs `pip install .[claude]` and ANTHROPIC_API_KEY."""

    def __init__(self, model: str):
        import anthropic  # optional dependency

        self.name = f"claude:{model}"
        self._model = model
        self._client = anthropic.Anthropic()

    def complete(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 1024,
    ) -> ModelResponse:
        kwargs: dict = {
            "model": self._model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ]
        start = time.perf_counter()
        resp = self._client.messages.create(**kwargs)
        latency = time.perf_counter() - start

        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = [
            ToolCall(name=b.name, arguments=dict(b.input), id=b.id)
            for b in resp.content
            if b.type == "tool_use"
        ]
        return ModelResponse(
            text=text,
            tool_calls=calls,
            usage=Usage(resp.usage.input_tokens, resp.usage.output_tokens),
            model=self.name,
            latency_s=latency,
        )
