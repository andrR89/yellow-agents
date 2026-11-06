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

## Phases

### Phase 1 — Emulator + state + MCP *(in progress)*
- [x] PyBoy wrapper: headless, buttons, save/load state, screenshot
- [x] RAM → JSON state from `pokeyellow.sym` (map, position, party, battle, badges, Pikachu)
- [x] Data tables extracted from pret/pokeyellow
- [x] MCP server with input validation
- [x] Unit tests with fake memory
- [ ] Validate with a real ROM: walk around Pallet Town via Claude Code
- [ ] Tune `HOLD_FRAMES` / `SETTLE_FRAMES` so one press = one tile, reliably
- [ ] Detect "text box open" / "menu open" in the state (so the model knows when to press A)

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

### Phase 7 — Capstone
- [ ] Live/timelapse with dashboard
- [ ] Write-up: what worked, what didn't, cost per badge per model
