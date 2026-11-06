# Roadmap

Each phase ends with something runnable and a number to report. The right-hand column maps it to
the curriculum modules, so by the end every module has a concrete deliverable.

| # | Curriculum module | Deliverable in this project | Phase |
|---|---|---|---|
| 1 | AI & LLM fundamentals | Benchmark report: 3–4 models (incl. a local one) on the same scenarios — success rate, cost, latency, tokens/turn. Plus screen (vision) vs RAM state as input. | 2 |
| 2 | Generative AI APIs & prompt engineering | Versioned prompts, tool calling with an action schema, validated structured output, prompt A/B via evals. | 2–3 |
| 3 | RAG | Index built from pokeyellow (types, moves, learnsets, trainers, maps) + a goal guide. Retrieval evaluated on its own (did it find the right chunk?). | 4 |
| 4 | MCP | Emulator MCP server, used from Claude Code, Claude Desktop and Codex. | 1 ✅ skeleton |
| 5 | Autonomous agents | Planner + navigator (A*) + battle agent, with memory notebook, context summarization and loop detection. Goal: beat Brock with no human input. | 5 |
| 6 | AI system architecture | Architecture doc + ADRs: code vs model boundary, cost-based routing, save-state checkpoints, fallbacks when the model fails or breaks the schema. | 3–5 |
| 7 | Fine-tuning & data processing | Data pipeline: thousands of battles from save states, cleaning, labels, train/test split. LoRA on a small local model vs the large model via prompting. | 6 |
| 8 | AI for DevOps | Headless emulator in Docker, eval scenarios in CI on every PR (fail on regression), traces (Langfuse), cost dashboard. | 3+ |
| 9 | Security & governance | Prompt injection via player/rival names, per-session spend cap and kill switch, decision audit log, agent model card. | 6 |
| 10 | Capstone | Timelapse/live run with a side panel (goal, reasoning, badges, cost), README results, technical write-up. | 7 |

## The showcase site (applies to every phase)

The real deliverable is a **live, animated page** that explains how the agent works and how each
problem was solved — the portfolio piece. It lives in `site/`, is published with GitHub Pages and
grows phase by phase. Every phase is only "done" when its section is on the site.

Each section follows the same shape:
1. **Problem** — what was hard, in one paragraph.
2. **How it works** — animated explanation of the mechanism.
3. **Decision** — options considered and why this one (links to the ADR).
4. **Result** — real numbers (success rate, frames, cost, latency) and what failed.

**Languages:** pt-BR, en, es, zh (Simplified Chinese) and ar (Arabic). Built in from site v1:
all UI text in per-locale JSON files (no hardcoded strings), `dir="rtl"` support for Arabic
(use CSS logical properties: `margin-inline-start`, not `margin-left`), fonts with CJK and
Arabic coverage, numbers and dates formatted per locale (`Intl`). pt-BR is the source language;
other locales are machine-translated and then reviewed.

**Final piece — "watch the AI play" (scope: at least until beating Brock):** an interactive
replay (and an exported video) of a real run: game screen on one side, and next to it what the
agent is doing to choose each action — current goal, state it read, what it retrieved (RAG),
options it considered, which model decided (local or Claude) and why, cost so far. Scrubbable
timeline, jump to key moments (first battle, catching Pokémon for Brock, the Brock fight).
Requires every run to record: frame number, screenshot, state JSON, prompt, model response,
chosen action, tokens and latency.

Rule: animations are driven by **real recorded data** (state snapshots, traces, benchmark
results exported as JSON by the agent), not hand-made mockups. **Project journal:** a timeline page built from `docs/sessions/*.md`. Each session shows its
goal, the problems found (symptom → cause → solution → evidence), decisions and numbers. It is
the running report of the whole project, from session 0 (planning) to beating the game.

Planned interactive pieces:
- RAM decoder: hex bytes from a real snapshot → highlighted fields → the JSON the model sees.
- MCP call flow: client → tool → emulator → state, step by step.
- Run replay: map with the agent's path, decision timeline with its reasoning, live cost counter.
- Model routing: which decisions went to the local model vs Claude, and why.
- Benchmark charts: Claude × GPT × local per scenario.

## Phases

### Phase 1 — Emulator + state + MCP *(in progress)*
- [x] PyBoy wrapper: headless, buttons, save/load state, screenshot
- [x] RAM → JSON state from `pokeyellow.sym` (map, position, party, battle, badges, Pikachu)
- [x] Data tables extracted from pret/pokeyellow
- [x] MCP server with input validation
- [x] Unit tests with fake memory
- [x] Validate with a real ROM: new game → Pallet Town → Pikachu, over the MCP stdio client and
      `tests/test_rom.py` (session 1)
- [ ] Same thing driven by Claude Code itself as the MCP client
- [x] One press = one tile, reliably: closed-loop walking on `wWalkCounter` replaced fixed
      `HOLD_FRAMES` / `SETTLE_FRAMES` ([ADR 0001](adr/0001-closed-loop-walking.md))
- [x] Detect "text box open" / "menu open": `screen` = overworld / text / menu / cutscene, the
      visible text and the item under the cursor, read from `wTileMap`

- [x] Export state snapshots + raw RAM bytes to JSON (`yellow-snapshot`, `site/data/snapshots/`)
- [x] Run recorder format (`recorder.py`: frame, screenshot, state, prompt, response, action,
      tokens, latency, cost); the MCP server records when `YELLOW_RUNS` is set
- [ ] Site v1: architecture overview, RAM → state decoder, MCP call flow

**Milestone:** Claude Code plays through MCP from a new game to receiving Pikachu.

### Phase 2 — First agent loop + benchmark
- [ ] Action schema: `press`, `walk(direction, tiles)`, `talk`, `use_move(slot)`, `switch(slot)`
- [ ] Simple loop: state → model → action → state, with cost/latency logging
- [ ] Scenario runner: from a save state, run N turns, score success
- [ ] Benchmark Claude vs OpenAI vs Ollama (local) on 3 scenarios

**Milestone:** beat the rival's Eevee in Oak's lab, unattended.

### Phase 3 — Navigation + evals in CI
- [ ] Collision grid per map (pokeyellow map data / `game_area_collision`)
- [ ] A* pathfinding → `go_to(map, x, y)` tool
- [ ] Scenario suite + GitHub Actions (small Claude set, or a self-hosted runner with the GPU)

### Phase 4 — Battle agent + RAG
- [ ] Type chart and move data as a retrievable knowledge base
- [ ] Battle-only agent on a cheaper/local model; retrieval evals

### Phase 5 — Long-horizon agent
- [ ] Planner with goals and a persistent notebook
- [ ] Context summarization, loop detection, auto checkpoints
- [ ] **Goal: Boulder Badge with no human input**

### Phase 6 — Fine-tuning + security
- [ ] Battle dataset generator (save states × random teams)
- [ ] LoRA (Unsloth) on a 7–8B model on the local 16 GB GPU; compare vs prompting
- [ ] Prompt injection tests through in-game names; spend cap; audit log; model card

### Phase 7 — The rest of the game, badge by badge
- [ ] One eval scenario per hard section: HMs, Rock Tunnel, Pokémon Tower, Safari Zone,
      Victory Road, Elite Four
- [ ] Dashboard: badges, in-game hours, cost, human interventions
- [ ] **Final goal: Elite Four + Champion with no human input**

### Phase 8 — Capstone
- [ ] Live/timelapse with dashboard
- [ ] Write-up: what worked, what didn't, cost per badge per model

## Future ideas (not commitments)

### Speedrun (after beating the game)
Metric: emulator frames from New Game to the target flag (deterministic, independent of model
latency). Levels, cheapest first:
1. Deterministic optimization: extract the route from a winning run, shortest paths with A*,
   fast text speed, battle animations off. This is the baseline to beat.
2. Learning between runs (reflection): the planner reads the last run's log and rewrites the plan;
   plot frames × attempts.
3. Route search with save states: the LLM proposes variants (e.g. Mankey vs Nidoran for Brock),
   parallel headless runs score them, keep/mutate the best ("LLM as optimizer").
4. Frame-level search / RL for RNG manipulation in battles and encounters (TAS-style).
Extras: behavior cloning of the best runs into the local model; with vs without human route
knowledge via RAG; auto-updated leaderboard in the README.

### Laya (small local decision model)
https://brainfunctioncollapse.com/laya — Apache-2.0, ~322M params, returns probabilities for
typed yes/no questions. Bad with numbers, so not for game decisions. Candidate experiments:
easy-vs-hard routing (local model vs Claude) and prompt-injection guard, compared against rules
and an LLM check. Read its SKILL.md fully before installing it.
