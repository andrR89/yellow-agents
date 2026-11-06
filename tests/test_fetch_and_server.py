import anyio
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from yellow_agent import mcp_server
from yellow_agent.models import load_model
from yellow_agent.tools.fetch_pret_data import parse_indexed_strings, parse_maps, parse_types


def test_parse_pokemon_names():
    asm = 'MonsterNames::\n\ttable_width 10\n\tdname "RHYDON"\n\tdname "KANGASKHAN"\n'
    assert parse_indexed_strings(asm, "dname") == {1: "RHYDON", 2: "KANGASKHAN"}


def test_parse_maps_uses_hex_comment():
    asm = "\tmap_const PALLET_TOWN,   10,  9 ; $00\n\tmap_const OAKS_LAB, 5, 6 ; $28\n"
    assert parse_maps(asm)[0x28] == {"name": "OAKS_LAB", "width": 5, "height": 6}


def test_parse_types_handles_gaps():
    asm = "\tconst NORMAL ; $00\n\tconst FIRE   ; $14\n\tconst PSYCHIC_TYPE ; $18\n"
    assert parse_types(asm) == {0x00: "NORMAL", 0x14: "FIRE", 0x18: "PSYCHIC"}


@pytest.mark.parametrize("name", ["../etc/passwd", "a/b", "", "x" * 65, "with space"])
def test_save_names_cannot_escape_saves_dir(name):
    with pytest.raises(ToolError):
        mcp_server._save_path(name)


def test_save_name_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("YELLOW_SAVES", str(tmp_path))
    assert mcp_server._save_path("before_brock-1") == tmp_path / "before_brock-1.state"


def test_press_buttons_validates_before_touching_emulator():
    with pytest.raises(ToolError, match="invalid buttons"):
        mcp_server.press_buttons(["a", "jump"])
    with pytest.raises(ToolError, match="at most"):
        mcp_server.press_buttons(["a"] * 31)


@pytest.mark.parametrize("player, rival", [("claude", "GEMINI"), ("CLAUDE", "GEMINI-2"), ("", "X")])
def test_new_game_validates_names_before_touching_emulator(player, rival):
    with pytest.raises(ToolError, match="name must be"):
        mcp_server.new_game(player, rival)
    assert mcp_server._emu is None


def test_validation_message_reaches_the_model():
    # A plain exception is treated as a crash by the MCP SDK and the client only sees
    # "Error executing tool ..."; the model needs the reason to correct itself.
    async def call() -> str:
        with pytest.raises(ToolError) as exc:
            await mcp_server.server.call_tool("press_buttons", {"buttons": ["jump"]})
        return str(exc.value)

    assert "invalid buttons" in anyio.run(call)


def test_model_spec_validation():
    with pytest.raises(ValueError):
        load_model("qwen3")
    with pytest.raises(ValueError, match="unknown provider"):
        load_model("mistral:large")
