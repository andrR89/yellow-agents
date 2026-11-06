# ADR 0001 — Closed-loop walking instead of fixed button timing

**Status:** accepted · 2026-11-06 · session 1

## Context

The MCP tool promises "one directional press = one tile". The skeleton pressed every button with
a fixed timing (`HOLD_FRAMES = 8`, then `SETTLE_FRAMES = 16`). On the real ROM, 8 moves that were
all possible (bedroom, fresh game) gave:

| hold + settle (frames) | tiles moved per press | correct |
|---|---|---|
| 8 + 16 (old default) | 1 1 1 1 1 0 1 1 | 7/8 |
| 8 + 8 | 0 1 1 1 1 1 0 1 | 6/8 |
| 16 + 0 | 0 1 1 1 1 1 1 0 | 6/8 |
| 4 + 12 | 0 1 0 1 1 0 0 1 | 4/8 |
| 2 + 14 | 0 0 1 0 0 1 0 0 | 2/8 |
| 1 + 15 / 1 + 20 | all 0 | 0/8 |

A frame-by-frame trace shows why no fixed value works: one step takes 16–18 frames,
`wWalkCounter` counts 7 → 0 during it, the coordinates only change on the last frame, and the
game only reads a new direction in the frames between steps. Where a press lands in that cycle
depends on everything that happened before.

## Decision

Directional presses are closed-loop, driven by RAM (`Emulator.step`):

1. Hold the direction until `wWalkCounter` becomes non-zero (the step started), at most 12 frames.
2. Release and run until `wWalkCounter` is 0 again (the step finished), at most 40 frames.
3. If `wCurMap` changed, the step went through a door/stairs: wait `WARP_SETTLE_FRAMES = 72`.
   Measured: input works again 64 frames after a stairs warp, never before.
4. Return `moved`, `blocked` (wall/NPC: the player only turns) or `warped`.

A, B, Start and Select keep the fixed 8 + 16 timing; in menus a direction never starts a walk,
so it behaves as a single cursor press (checked: Start menu and naming menu, one item per press).

## Consequences

- 37/37 steps of a scripted route (bedroom → stairs → living room → door → Pallet Town, incl.
  2 warps and 1 wall bump) land exactly where expected: `tests/test_rom.py`.
- A press now takes as long as the game needs (16–18 frames walking, ~90 with a warp) instead of
  a constant 24 frames. Benchmarks should count emulator frames, not presses.
- `WARP_SETTLE_FRAMES` was measured on stairs only. Doors worked with it too; if some warp
  (e.g. a cave, a cut-scene on arrival) needs longer, the next step will come back `blocked`
  and the eval scenario will show it.
