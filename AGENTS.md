# Conventions for coding agents

Read by Codex directly and by Claude Code through `CLAUDE.md`.

## Project
AI agent that plays Pokémon Yellow via PyBoy. Roadmap and module mapping: `docs/ROADMAP.md`.
Architecture and principles: `docs/ARCHITECTURE.md`.

## Rules
- Python ≥ 3.11, type hints everywhere, pydantic for data that crosses boundaries.
- RAM addresses come **only** from `pokeyellow.sym` via `SymbolTable`. Never hardcode addresses
  in logic; struct offsets go in named constants in `state.py`, citing pret's `macros/ram.asm`.
- Deterministic logic (pathfinding, parsing, timing) stays in code, not in prompts.
- Every MCP tool validates its inputs before touching the emulator.
- Never commit ROMs, saves or `data/generated/`.
- Tests must run without a ROM (use `tests/conftest.py`'s `FakeMemory`). Tests that need a ROM
  must be marked `@pytest.mark.rom` and skipped when `YELLOW_ROM` is unset.

## Before finishing a change
```bash
ruff check . && ruff format --check . && pytest
```
Update `docs/ROADMAP.md` checkboxes when a deliverable lands.
