"""Project persistence — save/load a complete Poneglyph project to JSON."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProjectMeta:
    name: str
    site: str
    engineer: str
    version: str = "2.0"


@dataclass
class Project:
    meta: ProjectMeta
    # Raw dicts mirror the dataclass structures; loaded into objects by the app
    network: dict[str, Any] = field(default_factory=dict)
    measurement_points: list[dict[str, Any]] = field(default_factory=list)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: Path) -> "Project":
        data = json.loads(path.read_text())
        meta = ProjectMeta(**data["meta"])
        return cls(
            meta=meta,
            network=data.get("network", {}),
            measurement_points=data.get("measurement_points", []),
        )
