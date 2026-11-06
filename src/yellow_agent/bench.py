"""Benchmark: models × scenarios, every run recorded, results for the site.

Each model plays as itself (CLAUDE, GPT, QWEN; the rival stays GEMINI) from the same
scripted start. Spend is capped per run and for the whole benchmark.

CLI::

    yellow-bench --models openrouter:anthropic/claude-haiku-5.5,ollama:qwen3:4b \\
                 --scenarios rival_battle,pikachu,route1 --budget 3 --site site
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from .agent import AgentRun, run_agent
from .recorder import RunRecorder, _git_commit
from .scenarios import SCENARIOS

DEFAULT_RUN_BUDGET = 0.75


class BenchResult(BaseModel):
    model: str
    scenario: str
    player_name: str
    run_id: str
    stop: str
    success: bool
    turns: int
    frames: int
    cost_usd: float
    input_tokens: int
    output_tokens: int
    model_latency_s: float
    invalid_actions: int
    no_tool_calls: int
    model_errors: int
    tools: dict[str, int]
    git_commit: str | None
    started_at: datetime


def player_name(model_spec: str) -> str:
    """The name the model plays under: 1-7 letters A-Z, as the game's naming screen allows."""
    s = model_spec.lower()
    for key, name in (("claude", "CLAUDE"), ("anthropic", "CLAUDE"), ("gpt", "GPT"),
                      ("openai", "GPT"), ("qwen", "QWEN"), ("llama", "LLAMA"),
                      ("gemma", "GEMMA"), ("mistral", "MISTRAL")):  # fmt: skip
        if key in s:
            return name
    letters = re.sub(r"[^A-Z]", "", model_spec.split(":")[-1].split("/")[-1].upper())
    return (letters or "AGENT")[:7]


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()


def run_one(model_spec: str, scenario_name: str, runs_dir: Path, budget_usd: float) -> BenchResult:
    from .emulator import Emulator
    from .models import load_model

    scenario = SCENARIOS[scenario_name]
    model = load_model(model_spec)
    name = player_name(model_spec)
    started = datetime.now(UTC)
    run_id = f"{started:%Y%m%d-%H%M%S}-{scenario_name}-{_slug(model_spec)}"[:64]
    emu = Emulator(
        os.environ["YELLOW_ROM"],
        sym=os.environ.get("YELLOW_SYM", "data/generated/pokeyellow.sym"),
        data_dir=os.environ.get("YELLOW_DATA", "data/generated"),
    )
    try:
        scenario.setup(emu, name)
        notes = json.dumps({"model": model_spec, "scenario": scenario_name, "goal": scenario.goal})
        recorder = RunRecorder.start(
            runs_dir, source="eval", start_state=scenario_name, run_id=run_id, notes=notes
        )
        try:
            run: AgentRun = run_agent(
                emu, model, scenario.goal, scenario.judge(),
                max_turns=scenario.max_turns, budget_usd=budget_usd, recorder=recorder,
            )  # fmt: skip
        finally:
            recorder.close()
    finally:
        emu.close()
    return BenchResult(
        model=model_spec,
        scenario=scenario_name,
        player_name=name,
        run_id=run_id,
        stop=run.stop,
        success=run.success,
        turns=run.turns,
        frames=run.frames,
        cost_usd=round(run.cost_usd, 6),
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        model_latency_s=round(run.model_latency_s, 2),
        invalid_actions=run.invalid_actions,
        no_tool_calls=run.no_tool_calls,
        model_errors=run.model_errors,
        tools=run.tools,
        git_commit=_git_commit(),
        started_at=started,
    )


def merge_into_site(results: list[BenchResult], site: Path, runs_dir: Path) -> Path:
    """site/data/benchmark.json keeps the latest result per (model, scenario); each run's replay
    goes to site/data/runs/ like any other recorded run."""
    from .site_data import write_replay

    out = site / "data" / "benchmark.json"
    old = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
    fresh = {(r.model, r.scenario) for r in results}
    kept = [r for r in old if (r["model"], r["scenario"]) not in fresh]
    merged = kept + [r.model_dump(mode="json") for r in results]
    merged.sort(key=lambda r: (r["scenario"], r["model"]))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for r in results:
        write_replay(runs_dir / r.run_id, site)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Run models on the eval scenarios.")
    parser.add_argument("--models", required=True, help="comma-separated model specs")
    parser.add_argument("--scenarios", default=",".join(SCENARIOS))
    parser.add_argument("--budget", type=float, default=3.0, help="USD cap for the whole bench")
    parser.add_argument("--run-budget", type=float, default=DEFAULT_RUN_BUDGET)
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    parser.add_argument("--site", type=Path, help="merge results + replays into the site")
    args = parser.parse_args()

    rom = os.environ.get("YELLOW_ROM")
    if not rom or not Path(rom).is_file():
        parser.error("set YELLOW_ROM to your own Pokémon Yellow dump")
    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    unknown = [s for s in scenarios if s not in SCENARIOS]
    if unknown:
        parser.error(f"unknown scenarios {unknown}; known: {list(SCENARIOS)}")
    models = [m.strip() for m in args.models.split(",") if m.strip()]

    spent = 0.0
    results: list[BenchResult] = []
    for scenario in scenarios:
        for model in models:
            left = args.budget - spent
            if left <= 0:
                print(f"budget of ${args.budget:.2f} spent; stopping")
                break
            r = run_one(model, scenario, args.runs_dir, min(args.run_budget, left))
            spent += r.cost_usd
            results.append(r)
            print(
                f"{scenario:13} {model:45} {r.stop:11} turns={r.turns:3} "
                f"frames={r.frames:6} cost=${r.cost_usd:.4f} invalid={r.invalid_actions}"
            )
    print(f"total spent: ${spent:.4f}")
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    args.runs_dir.mkdir(parents=True, exist_ok=True)
    summary = args.runs_dir / f"bench-{stamp}.json"
    summary.write_text(json.dumps([r.model_dump(mode="json") for r in results], indent=1) + "\n")
    print(f"wrote {summary}")
    if args.site:
        print(f"wrote {merge_into_site(results, args.site, args.runs_dir)}")


if __name__ == "__main__":
    main()
