"""Ollama's native /api/chat (standard library only).

Not the OpenAI-compatible endpoint: there qwen3 keeps thinking whatever we send
(`think: false`, `reasoning_effort`), runs out of tokens and never calls a tool (session 5).
The native API honours `think: false`, and takes the context size and keep-alive per request:
a small context keeps the model's GPU footprint small (see tools/gpu_guard.py).
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Any

from .base import Message, ModelResponse, ToolCall, ToolSpec, Usage

OLLAMA_URL = "http://localhost:11434"
NUM_CTX = 4096  # one turn's prompt is ~1.5k tokens; the server default here is 32k
KEEP_ALIVE = "2m"  # unload soon after a run, freeing the GPU


def build_chat(model: str, system: str, messages: list[Message], tools: list[ToolSpec] | None,
               max_tokens: int) -> dict[str, Any]:  # fmt: skip
    body: dict[str, Any] = {
        "model": model,
        "stream": False,
        "think": False,
        "keep_alive": KEEP_ALIVE,
        "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": max_tokens},
        "messages": [{"role": "system", "content": system}]
        + [{"role": m.role, "content": m.content} for m in messages],
    }
    if tools:
        body["tools"] = [
            {"type": "function", "function": {"name": t.name, "description": t.description,
                                              "parameters": t.parameters}}
            for t in tools
        ]  # fmt: skip
    return body


def parse_chat(data: dict[str, Any], name: str, latency_s: float) -> ModelResponse:
    msg = data.get("message") or {}
    calls = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"_raw": args}
        calls.append(ToolCall(name=fn.get("name", ""), arguments=args or {}, id=tc.get("id")))
    return ModelResponse(
        text=msg.get("content") or "",
        tool_calls=calls,
        usage=Usage(data.get("prompt_eval_count", 0), data.get("eval_count", 0)),
        model=name,
        latency_s=latency_s,
        cost_usd=0.0,
    )


class OllamaModel:
    def __init__(self, model: str):
        self.name = f"ollama:{model}"
        self._model = model
        self._url = os.environ.get("OLLAMA_HOST_URL", OLLAMA_URL).rstrip("/") + "/api/chat"

    def complete(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 1024,
    ) -> ModelResponse:
        body = json.dumps(build_chat(self._model, system, messages, tools, max_tokens)).encode()
        req = urllib.request.Request(self._url, data=body,
                                     headers={"Content-Type": "application/json"})  # fmt: skip
        start = time.perf_counter()
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.load(resp)
        return parse_chat(data, self.name, time.perf_counter() - start)
