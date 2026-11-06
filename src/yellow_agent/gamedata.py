"""Lookup tables extracted from pret/pokeyellow (see tools/fetch_pret_data.py)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


def _load(path: Path) -> dict[int, object]:
    if not path.exists():
        return {}
    return {int(k): v for k, v in json.loads(path.read_text(encoding="utf-8")).items()}


@dataclass
class GameData:
    pokemon: dict[int, str] = field(default_factory=dict)
    moves: dict[int, str] = field(default_factory=dict)
    maps: dict[int, dict] = field(default_factory=dict)
    types: dict[int, str] = field(default_factory=dict)

    @classmethod
    def load(cls, directory: str | Path = "data/generated") -> GameData:
        d = Path(directory)
        return cls(
            pokemon=_load(d / "pokemon.json"),  # type: ignore[arg-type]
            moves=_load(d / "moves.json"),  # type: ignore[arg-type]
            maps=_load(d / "maps.json"),  # type: ignore[arg-type]
            types=_load(d / "types.json"),  # type: ignore[arg-type]
        )

    def species(self, index: int) -> str:
        return self.pokemon.get(index, f"SPECIES_{index:#04x}")

    def move(self, move_id: int) -> str | None:
        if move_id == 0:
            return None
        return self.moves.get(move_id, f"MOVE_{move_id:#04x}")

    def map_name(self, map_id: int) -> str:
        entry = self.maps.get(map_id)
        return entry["name"] if entry else f"MAP_{map_id:#04x}"

    def type_name(self, type_id: int) -> str:
        return self.types.get(type_id, f"TYPE_{type_id:#04x}")
