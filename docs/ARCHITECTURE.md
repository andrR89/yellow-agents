# Architecture

## Layers

1. **Emulator** (`emulator.py`): PyBoy headless at unlimited speed. Owns input timing and save
   states. No AI here.
2. **State** (`state.py`): reads RAM via `pokeyellow.sym` into pydantic models. Pure function of
   memory, unit-tested with a fake memory. This is the agent's primary "eyes"; the screenshot is
   a fallback for menus and dialogue.
3. **Tools** (`mcp_server.py`): the action surface. Validated inputs (button whitelist, bounded
   sequences, save names that can't become paths). Same tools for any MCP client and, later, for
   our own agent loop.
4. **Models** (`models/`): one `ChatModel` interface; Claude, OpenAI and Ollama (via the
   OpenAI-compatible endpoint) are implementations chosen by a `provider:model` string.
5. **Agent** *(phase 2+)*: planner / navigator / battle, memory, routing.

## Principles

- **Code does what is deterministic.** Pathfinding, RAM parsing, input timing and rules are
  never delegated to a model.
- **Models decide.** Strategy, goal selection and battle choices.
- **Everything reproducible.** Scenarios start from save states; runs log state, prompt, response,
  tokens and latency, so any decision can be replayed.
- **Cheap by default.** Local model for high-frequency decisions, frontier model for planning and
  hard cases; a spend cap per session.

## Notes on Pokémon Yellow specifics

- RAM addresses differ from Red. Always use the Yellow `.sym`.
- Species bytes are **internal indexes** (e.g. PIKACHU = `0x54`), not Pokédex numbers.
- Pikachu follows the player; facing it and pressing A opens an interaction.
- `wPikachuHappiness` is part of the state on purpose: it affects Pikachu's behaviour.

## Decision records

Put ADRs in `docs/adr/NNNN-title.md` (context → decision → consequences).
