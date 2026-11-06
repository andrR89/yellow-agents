# Architecture

## Layers

1. **Emulator** (`emulator.py`): PyBoy headless at unlimited speed. Owns input timing and save
   states. No AI here. Directions are closed-loop on `wWalkCounter`
   ([ADR 0001](adr/0001-closed-loop-walking.md)); every action renders its last frame, so
   screenshots never advance the game.
2. **State** (`state.py`): reads RAM via `pokeyellow.sym` into pydantic models. Pure function of
   memory, unit-tested with a fake memory. This is the agent's primary "eyes". It includes
   `screen`, decoded from the `wTileMap` tile buffer: overworld / text / menu / cutscene, the
   visible text and the menu item under the cursor, so dialogue and menus need no screenshot.
3. **Tools** (`mcp_server.py`): the action surface. Validated inputs (button whitelist, bounded
   sequences, save names that can't become paths). Same tools for any MCP client and, later, for
   our own agent loop.
4. **Models** (`models/`): one `ChatModel` interface; Claude, OpenAI and Ollama (via the
   OpenAI-compatible endpoint) are implementations chosen by a `provider:model` string.
5. **Agent** *(phase 2+)*: planner / navigator / battle, memory, routing.
6. **Recording** (`recorder.py`, `snapshot.py`): every run is a JSONL file (header + one line per
   action: frame, state, action, screenshot, prompt/response, tokens, latency, cost); RAM
   snapshots pair raw bytes with the fields they become. Both feed the showcase site.
7. **Baseline & site data** (`baseline.py`, `site_data.py`, `newgame.py`): a scripted, model-free
   run from power-on to Pikachu (the yardstick: frames per milestone), and the exporters behind
   every number on the site. `Emulator.on_frame` streams every frame (video) without changing
   the game.

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
