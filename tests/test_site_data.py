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
