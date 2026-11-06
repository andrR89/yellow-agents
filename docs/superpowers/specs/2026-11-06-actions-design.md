# High-level actions (Phase 2, sub-project 1)

Status: approved 2026-11-06. Next: implementation plan.

## Problem

In session 3, Claude Code needed 107 MCP calls to go from a new game to Pikachu (frame 19,138 vs
the script's 11,470). 51 calls were `wait`; most of the rest pressed one A per line of text,
because an A pressed while text is still printing is dropped. A model loop billed per call
cannot play like that. Phase 2's loop needs a small set of actions that each do one meaningful
thing and say what happened.

## Scope

In: `advance_text`, `walk`, `talk`, `choose`, `use_move`, an `ActionResult` model, MCP tools
for each, the species-0 party fix, tests, and a re-run of the Pikachu route with the new actions.

Out: `switch(slot)` (Pikachu is the only Pokémon until Phase 4), pathfinding (`go_to`, Phase 3),
the agent loop itself (sub-project 2). `press_buttons` and `wait` stay as they are.

## Design

### Module

`src/yellow_agent/actions.py`. Functions take an `Emulator` and return `ActionResult`. The MCP
server and, later, the agent loop call the same functions; no logic lives in `mcp_server.py`
beyond input validation and recording.

Pure decision helpers (no emulator) sit next to them so they are unit-testable with plain tile
lists or `FakeMemory`:

- `text_ready(tiles, previous_tiles, stable_frames) -> bool`
- `cursor_moves(screen, target) -> list[Button]` (or an error if `target` is not on screen)

### ActionResult

```python
class StopReason(StrEnum):
    MENU = "menu"  # a choice is on screen (cursor ▶)
    OVERWORLD = "overworld"  # the player has control again
    BATTLE_MENU = "battle_menu"  # FIGHT/PKMN/ITEM/RUN is up
    BLOCKED = "blocked"  # walk: something in the way
    WARPED = "warped"  # walk: the map changed
    TEXT = "text"  # walk: a text box opened (NPC, sign, trainer)
    SCRIPT = "script"  # walk: the game took control (wJoyIgnore != 0), e.g. Oak
    # stopping you; its text comes a few frames later
    BATTLE = "battle"  # walk: a battle started
    DONE = "done"  # walk: all tiles walked
    LIMIT = "limit"  # frame or press cap reached; the state says where we are


class ActionResult(BaseModel):
    action: dict[str, Any]  # e.g. {"tool": "walk", "direction": "up", "tiles": 5}
    stop: StopReason
    frames: int  # emulator frames the action took
    presses: int  # buttons actually pressed
    tiles: int | None = None  # walk only: tiles moved
    transcript: list[str] = []  # text lines shown during the action, in order, deduplicated
    state: GameState  # state after the action
```

The MCP tools return `ActionResult` as JSON. The recorder stores `action` as the step's action
and puts `stop`, `frames`, `presses`, `tiles` and `transcript` in `RunStep.extra`.

### When is text ready for A

Press A when the screen is `text` and either:

1. the ▼ tile (`MORE_TEXT = 0xEE`) is in the text box area of `wTileMap`, or
2. `wTileMap` has not changed for `STABLE_FRAMES` (30) frames (battle messages without ▼).

Checked every frame. After each A, wait at least `HOLD_FRAMES + SETTLE_FRAMES` before checking
again, so the same ▼ is not pressed twice. Rejected alternatives: fixed timing (wastes frames,
breaks on long text) and the text engine's `hDownArrowBlinkCount1/2` (undocumented semantics).

### Actions

- **`advance_text(max_frames=3000)`**: while the screen is `text`, wait until ready, press A,
  append new lines to the transcript. Between text boxes, scripted scenes (Oak walking, the
  rival grabbing the ball) show the overworld while the game ignores input: as long as
  `wJoyIgnore != 0` (the signal `baseline.py` already uses), keep waiting instead of stopping.
  Stops on `menu`, `battle_menu`, `overworld` (input enabled and no text for `STABLE_FRAMES`)
  or `limit`. If called on an overworld with input enabled, returns at once with `frames=0`.
- **`walk(direction, tiles)`**: `tiles` 1–20. Repeats `Emulator.step`. Stops early on `blocked`,
  `warped`, `battle` (`wIsInBattle` became non-zero), `text` (screen became text) or `script`
  (input locked by a script); otherwise `done`. Only valid when the screen is `overworld`.
- **`talk()`**: only valid on `overworld`. Presses A, then `advance_text`. If no text opens within
  `STABLE_FRAMES`, stops with `overworld` and an empty transcript (nobody there).
- **`choose(item)`**: only valid on `menu` / `battle_menu`. `item` must match a menu item visible
  on screen (case-insensitive). Moves the cursor with up/down (left/right for the two-column
  battle menu) until `screen.cursor == item`, presses A, then `advance_text`. Gives up with an
  error after `MAX_CURSOR_MOVES` (10) without reaching the item.
- **`use_move(slot)`**: `slot` 1–4. Only valid on `battle_menu`. Validates that the slot has a
  move with PP > 0 (from `battle.player_mon.moves`). Chooses FIGHT, moves to the slot, presses A,
  then `advance_text` through the turn. Stops on the next `battle_menu`, or `overworld` / `text`
  when the battle ends.

`battle_menu` is detected from the screen: kind `menu` with `FIGHT` among the visible lines, and
`battle.kind != none`.

### Validation

All inputs are validated before touching the emulator (direction whitelist, `tiles` and `slot`
ranges, `item` present on screen, the screen kind each action needs). MCP tools raise
`ToolError` with the reason, as the existing tools do.

### Party fix

`StateReader.party()` skips entries whose species byte is 0. While the game is writing a
received Pokémon, `wPartyCount` is already incremented but the struct is still empty (session 3,
steps 102–104).

## Testing

Without a ROM:
- `text_ready`: ▼ present → ready; text still changing → not ready; stable for 30 frames → ready.
- `cursor_moves`: YES→NO is one `down`; an item not on screen is an error; the battle menu grid.
- Validation of every action's inputs and required screen kind.
- `party()` skips a species-0 entry (`FakeMemory`).

With a ROM (`@pytest.mark.rom`):
- From a new game, the Pikachu route using only `walk`, `advance_text`, `talk` and `choose`
  ends with PIKACHU in the party; the test records calls and frames.
- `walk` into a wall stops with `blocked` after 0 tiles.

## Result for the site

`yellow-baseline`-style numbers for the new route: MCP-level calls and frames to Pikachu with the
new actions, against session 3's 107 calls and 19,138 frames. Shown in the replay section once
the run exists.
