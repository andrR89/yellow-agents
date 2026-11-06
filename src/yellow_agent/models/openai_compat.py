from __future__ import annotations

import json
import time

from .base import Message, ModelResponse, ToolCall, ToolSpec, Usage

OLLAMA_BASE_URL = "http://localhost:11434/v1"


class OpenAICompatModel:
    """OpenAI Chat Completions API — also used for Ollama's OpenAI-compatible endpoint.

    Needs `pip install .[openai]`. For OpenAI set OPENAI_API_KEY; for Ollama nothing.
    """

    def __init__(self, model: str, base_url: str | None = None, provider: str = "openai"):
        import openai  # optional dependency

        self.name = f"{provider}:{model}"
        self._model = model
        api_key = "ollama" if provider == "ollama" else None  # Ollama ignores the key
        self._client = openai.OpenAI(base_url=base_url, api_key=api_key)

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
            "messages": [{"role": "system", "content": system}]
            + [{"role": m.role, "content": m.content} for m in messages],
        }
        if tools:
            kwargs["tools"] = [
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
        start = time.perf_counter()
        resp = self._client.chat.completions.create(**kwargs)
        latency = time.perf_counter() - start

        msg = resp.choices[0].message
        calls: list[ToolCall] = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}  # surfaced to the agent as an error
            calls.append(ToolCall(name=tc.function.name, arguments=args, id=tc.id))
        usage = resp.usage
        return ModelResponse(
            text=msg.content or "",
            tool_calls=calls,
            usage=Usage(usage.prompt_tokens, usage.completion_tokens) if usage else Usage(),
            model=self.name,
            latency_s=latency,
        )
