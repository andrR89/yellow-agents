"""The current map as a walkable grid, its exits and the people on it; A* paths on it.

How the game decides a cell is walkable (pret: home/overworld.asm, CheckTilePassable): a map is
made of 4x4-tile blocks (2x2 player cells); a cell is walkable when the tile at its bottom-left
corner is in the tileset's collision list (terminated by $FF), or is the tileset's grass tile.
Blocks come from wOverworldMap (the map plus a 3-block border); block tiles come from the
tileset's blockset in ROM (wTilesetBank : wTilesetBlocksPtr). People (sprite slots with a
picture that are shown) and Pikachu block the cell they stand on. Warp cells always count as
walkable: an interior's exit tiles at the bottom wall are not in the collision list, but the
player steps onto them and walks out (Oak's lab, session 8).

Not modelled yet: ledges (one-way jumps) and tile-pair collisions (elevation edges in caves).
"""

from __future__ import annotations

import heapq
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from pydantic import BaseModel

BORDER_BLOCKS = 3  # wOverworldMap pads the map with 3 blocks on each side
BLOCK_TILES = 4  # a block is 4x4 tiles = 2x2 cells
SPRITE_SLOTS = 16  # slot 0 = player, 1-14 = people, 15 = Pikachu (Yellow)
SPRITE_STRUCT = 0x10
SPRITE_IMAGE_INDEX = 0x02  # wSpriteStateData1: $FF = hidden (missable object not shown)
SPRITE_HIDDEN = 0xFF
SPRITE_MAP_Y = 0x04  # wSpriteStateData2: MapY / MapX hold the coordinate + 4
SPRITE_MAP_X = 0x05
SPRITE_COORD_OFFSET = 4
WARP_STRUCT = 4  # wWarpEntries: y, x, destination warp id, destination map
COLLISION_LIST_MAX = 0x180
COLLISION_LABEL = "Overworld_Coll"  # its bank holds every tileset's collision list
LAST_MAP = 0xFF  # a warp to "the map you came from" (house doors lead outside)
# wCurMapConnections bits (pret: constants/map_data_constants.asm)
CONNECTIONS = (("north", 3, "wNorthConnectedMap"), ("south", 2, "wSouthConnectedMap"),
               ("west", 1, "wWestConnectedMap"), ("east", 0, "wEastConnectedMap"))  # fmt: skip
DIRECTIONS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


class Exit(BaseModel):
    kind: str  # "warp" (door, stairs, mat) or "edge" (walk off this side of the map)
    to: str  # destination map name ("outside" for a warp back to the previous map)
    x: int | None = None  # warps: the cell to step on
    y: int | None = None
    side: str | None = None  # edges: north / south / west / east


class Person(BaseModel):
    x: int
    y: int
    who: str  # "pikachu" or "person"


@dataclass
class MapGrid:
    width: int  # in cells
    height: int
    walkable: list[list[bool]]  # [y][x]
    exits: list[Exit] = field(default_factory=list)
    people: list[Person] = field(default_factory=list)

    def free(self, x: int, y: int, *, ignore_people: bool = False) -> bool:
        if not (0 <= x < self.width and 0 <= y < self.height and self.walkable[y][x]):
            return False
        return ignore_people or all((p.x, p.y) != (x, y) for p in self.people)

    def ascii(self, here: tuple[int, int] | None = None) -> list[str]:
        rows = [["." if c else "#" for c in row] for row in self.walkable]
        for p in self.people:
            if 0 <= p.y < self.height and 0 <= p.x < self.width:
                rows[p.y][p.x] = "P" if p.who == "pikachu" else "N"
        for e in self.exits:
            if e.kind == "warp" and e.x is not None and e.y is not None:
                if 0 <= e.y < self.height and 0 <= e.x < self.width:
                    rows[e.y][e.x] = "D"
        if here and 0 <= here[1] < self.height and 0 <= here[0] < self.width:
            rows[here[1]][here[0]] = "@"
        return ["".join(r) for r in rows]


def walkable_cells(
    blocks: Callable[[int, int], int],  # (block x, block y) -> block id
    width_blocks: int,
    height_blocks: int,
    block_tile: Callable[[int, int], int],  # (block id, tile index 0-15) -> tile id
    passable: set[int],
) -> list[list[bool]]:
    """Pure: the cell grid from block ids, blockset tiles and the passable tile ids."""
    grid = []
    for cy in range(height_blocks * 2):
        row = []
        for cx in range(width_blocks * 2):
            block = blocks(cx // 2, cy // 2)
            sub_x, sub_y = cx % 2, cy % 2
            bottom_left = (sub_y * 2 + 1) * BLOCK_TILES + sub_x * 2
            row.append(block_tile(block, bottom_left) in passable)
        grid.append(row)
    return grid


def read_collision_list(read_u8: Callable[[int], int], ptr: int) -> set[int]:
    tiles = set()
    for i in range(COLLISION_LIST_MAX):
        t = read_u8(ptr + i)
        if t == 0xFF:
            break
        tiles.add(t)
    return tiles


def find_path(grid: MapGrid, start: tuple[int, int], goal: tuple[int, int]) -> list[str] | None:
    """A* over walkable cells (4 directions). People block, except on the goal itself.

    Returns the directions to walk, [] when already there, None when there is no way."""
    if start == goal:
        return []
    if not grid.free(*goal, ignore_people=True):
        return None

    def h(p: tuple[int, int]) -> int:
        return abs(p[0] - goal[0]) + abs(p[1] - goal[1])

    frontier: list[tuple[int, int, tuple[int, int]]] = [(h(start), 0, start)]
    came: dict[tuple[int, int], tuple[tuple[int, int], str] | None] = {start: None}
    cost = {start: 0}
    while frontier:
        _, g, cur = heapq.heappop(frontier)
        if cur == goal:
            break
        if g > cost[cur]:
            continue
        for name, (dx, dy) in DIRECTIONS.items():
            nxt = (cur[0] + dx, cur[1] + dy)
            if not grid.free(*nxt, ignore_people=nxt == goal):
                continue
            if g + 1 < cost.get(nxt, 1 << 30):
                cost[nxt] = g + 1
                came[nxt] = (cur, name)
                heapq.heappush(frontier, (g + 1 + h(nxt), g + 1, nxt))
    if goal not in came:
        return None
    path = []
    node = goal
    while (step := came[node]) is not None:
        node, name = step
        path.append(name)
    return path[::-1]


def runs(directions: Iterable[str]) -> list[tuple[str, int]]:
    """["up","up","left"] -> [("up", 2), ("left", 1)]"""
    out: list[tuple[str, int]] = []
    for d in directions:
        if out and out[-1][0] == d:
            out[-1] = (d, out[-1][1] + 1)
        else:
            out.append((d, 1))
    return out
