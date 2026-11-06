"""Model factory: "claude:<model>", "openai:<model>", "openrouter:<vendor/model>" or
"ollama:<model>"."""

from __future__ import annotations

import os

from .base import ChatModel, Message, ModelResponse, ToolCall, ToolSpec, Usage

__all__ = ["ChatModel", "Message", "ModelResponse", "ToolCall", "ToolSpec", "Usage", "load_model"]


def load_model(spec: str) -> ChatModel:
    """Build a model from a spec string, e.g. ``ollama:qwen3:8b``."""
    provider, sep, model = spec.partition(":")
    if not sep or not model:
        raise ValueError(f"model spec must be 'provider:model', got {spec!r}")
    if provider == "claude":
        from .claude import ClaudeModel

        return ClaudeModel(model)
    if provider == "openai":
        from .openai_compat import OpenAICompatModel

        return OpenAICompatModel(model, provider="openai")
    if provider == "openrouter":
        from .openai_compat import OPENROUTER_BASE_URL, OpenAICompatModel

        return OpenAICompatModel(model, base_url=OPENROUTER_BASE_URL, provider="openrouter")
    if provider == "ollama":
        from .openai_compat import OLLAMA_BASE_URL, OpenAICompatModel

        base = os.environ.get("OLLAMA_BASE_URL", OLLAMA_BASE_URL)
        return OpenAICompatModel(model, base_url=base, provider="ollama")
    raise ValueError(f"unknown provider {provider!r} (use claude, openai, openrouter or ollama)")
