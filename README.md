# yellow-agent

An AI agent that plays **Pokémon Yellow** through the [PyBoy](https://github.com/Baekalfen/PyBoy) emulator.

It's a study and portfolio project: every module of an applied AI engineering curriculum (LLMs,
prompting, RAG, MCP, agents, system architecture, fine-tuning, AI for DevOps, security) gets a
concrete, measurable deliverable here. See [docs/ROADMAP.md](docs/ROADMAP.md).

## Why Pokémon Yellow?

- **Long-horizon:** hours of play, dozens of goals, a lot of context to manage.
- **Measurable:** badges, steps, battles won, cost per badge.
- **Deterministic:** save states make every scenario reproducible, so evals work like unit tests.
- **Fully documented:** [pret/pokeyellow](https://github.com/pret/pokeyellow) is a complete
  disassembly, so the agent reads exact RAM symbols instead of guessing from pixels.
- **Harder than Red:** Pikachu won't evolve or stay in its ball, and it's weak against Brock.
  The agent has to *plan*.

## Architecture (short)

```
 Claude / OpenAI / Ollama (local)          ← swappable through one ChatModel interface
            │
       agent loop  (planner · navigator · battle)      [phase 3+]
            │  tools
       MCP server  ──────────────  Claude Code / Claude Desktop / Codex can play too
            │
       Emulator (PyBoy, headless) ── StateReader (RAM → JSON via pokeyellow.sym)
```

Rule: **deterministic work stays in code** (pathfinding, RAM parsing, input timing);
**the model makes decisions**. Details in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Setup

```bash
git clone <this repo> && cd yellow-agent
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,claude,openai]"

yellow-fetch-data            # pokeyellow.sym + species/moves/maps/types tables → data/generated/
```

You need **your own dump** of a Pokémon Yellow cartridge (`.gbc`). ROMs are never committed
(see `.gitignore`).

### Play it from Claude Code

```bash
claude mcp add yellow -e YELLOW_ROM=/path/to/pokeyellow.gbc -- yellow-mcp
```

…then ask Claude Code to `get_state` and start playing. Codex CLI and Claude Desktop work the same
way: any MCP client can launch `yellow-mcp` over stdio.

### MCP tools

| Tool | What it does |
|---|---|
| `get_state` | Map, x/y, facing, party (species, level, HP, moves/PP), badges, money, Pikachu happiness, battle |
| `press_buttons` | Press up to 30 buttons in order; returns the new state |
| `wait` | Run frames without input |
| `screenshot` | PNG of the screen (for menus/dialogue) |
| `save_state` / `load_state` / `list_states` | Named checkpoints |

## Models

`load_model("claude:claude-sonnet-5-5")`, `load_model("openai:<model>")` or
`load_model("ollama:qwen3:8b")`. Ollama goes through its OpenAI-compatible endpoint, so a local
GPU model is a drop-in replacement. See `.env.example`.

## Development

```bash
pytest          # no ROM needed: state parsing is tested against a fake memory
ruff check .
```

`AGENTS.md` holds the conventions for coding agents (Claude Code reads it through `CLAUDE.md`,
Codex reads it directly).

## Credits

- [pret/pokeyellow](https://github.com/pret/pokeyellow) for the disassembly and symbols.
- [PyBoy](https://github.com/Baekalfen/PyBoy) for the emulator.
- Inspired by *Claude Plays Pokémon* and Peter Whidden's RL work on Pokémon Red.

Pokémon is © Nintendo / Creatures / GAME FREAK. This project ships no game assets or ROMs.
