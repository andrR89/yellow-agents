from pathlib import Path

from yellow_agent.site_data import export_sessions, parse_frontmatter

ROOT = Path(__file__).resolve().parent.parent


def test_frontmatter_types():
    meta, body = parse_frontmatter(
        '---\nsessao: 2\ntitulo: "A: b # c"\nduracao_h: null   # não medido\n'
        "custo_usd: 0.00\ncommits: [abc1234, def5678]\nmarco: null\n---\n\n## Objetivo\nx\n"
    )
    assert meta == {
        "sessao": 2,
        "titulo": "A: b # c",
        "duracao_h": None,
        "custo_usd": 0.0,
        "commits": ["abc1234", "def5678"],
        "marco": None,
    }
    assert body == "## Objetivo\nx\n"


def test_real_sessions_parse_in_order():
    sessions = export_sessions(ROOT / "docs/sessions")
    numbers = [s.meta["sessao"] for s in sessions]
    assert numbers == sorted(numbers) and numbers[0] == 0
    assert all(s.meta["titulo"] and s.body.startswith("## Objetivo") for s in sessions)


def _keys(obj, prefix=""):
    if isinstance(obj, dict):
        return {k for key, v in obj.items() for k in _keys(v, f"{prefix}{key}.")} | {prefix}
    if isinstance(obj, list):
        return {k for i, v in enumerate(obj) for k in _keys(v, f"{prefix}{i}.")} | {prefix}
    return {prefix}


def test_every_locale_has_the_same_keys_as_pt_br():
    import json

    i18n = ROOT / "site/i18n"
    source = _keys(json.loads((i18n / "pt-BR.json").read_text(encoding="utf-8")))
    for path in i18n.glob("*.json"):
        assert _keys(json.loads(path.read_text(encoding="utf-8"))) == source, path.name


# -- recorded run -> replay ----------------------------------------------------


def _st(map_name, x, y, kind="overworld", lines=(), pikachu=False):
    from yellow_agent.state import Battle, BattleKind, GameState, Mon, Screen

    party = [Mon(species="PIKACHU", level=5, hp=19, max_hp=19, status="ok", types=[], moves=[])]
    return GameState(
        player_name="CLAUDE",
        rival_name="GEMINI",
        map_id=0,
        map_name=map_name,
        x=x,
        y=y,
        facing="up",
        money=3000,
        badges=[],
        pikachu_happiness=90,
        pikachu_mood=128,
        party=party if pikachu else [],
        battle=Battle(kind=BattleKind.NONE),
        screen=Screen(kind=kind, lines=list(lines)),
    )


def _record(tmp_path):
    from yellow_agent.recorder import RunRecorder

    rec = RunRecorder.start(tmp_path / "runs", source="mcp", run_id="r1")
    script = [
        (100, _st("REDS_HOUSE_2F", 3, 6), {"tool": "new_game"}),
        (200, _st("PALLET_TOWN", 5, 6), {"tool": "press_buttons", "buttons": ["down"]}),
        (300, _st("PALLET_TOWN", 10, 0), {"tool": "press_buttons", "buttons": ["up"]}),
        (400, _st("PALLET_TOWN", 10, 0, "text", ["OAK: Hey!"]), {"tool": "wait", "frames": 60}),
        (500, _st("PALLET_TOWN", 10, 0, "menu", ["FIGHT PKMN"]), {"tool": "wait"}),
        (600, _st("OAKS_LAB", 5, 5), {"tool": "wait"}),
        # Pikachu in the party but a text box still open: not the milestone yet
        (700, _st("OAKS_LAB", 5, 3, "text", ["nickname?"], pikachu=True), {"tool": "wait"}),
        (800, _st("OAKS_LAB", 5, 3, pikachu=True), {"tool": "press_buttons", "buttons": ["a"]}),
    ]
    for frame, state, action in script:
        rec.record(frame=frame, state=state, action=action, screenshot_png=b"\x89PNG")
    rec.close()
    return rec.run_dir


def test_run_milestones_follow_the_baseline_rules(tmp_path):
    from yellow_agent.recorder import load_run
    from yellow_agent.site_data import run_milestones

    _, steps = load_run(_record(tmp_path))
    got = {m["name"]: m["frame"] for m in run_milestones(steps)}
    assert got == {
        "bedroom": 100,
        "pallet_town": 200,
        "north_exit": 300,
        "oak_stops_you": 400,
        "oak_battle_menu": 500,
        "oaks_lab": 600,
        "got_pikachu": 800,
    }


def test_export_run_copies_screens_and_counts_actions(tmp_path):
    from yellow_agent.site_data import export_run

    site = tmp_path / "site"
    replay = export_run(_record(tmp_path), site)
    assert replay.total_frames == 800 and replay.start_frame == 100
    assert replay.actions == {"new_game": 1, "press_buttons": 3, "wait": 4}
    assert replay.wait_frames == 60
    assert replay.steps[-1].party == ["PIKACHU Lv5"]
    shot = replay.steps[0].screenshot
    assert shot == "media/runs/r1/000000.png" and (site / shot).read_bytes() == b"\x89PNG"
