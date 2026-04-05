from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_KEYMAP_PATH = Path(__file__).parent / "default_keymap.json"


@dataclass
class Keymap:
    gameplay: dict[str, str] = field(default_factory=dict)
    hotbar: dict[str, str] = field(default_factory=dict)
    map: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path | None = None) -> Keymap:
        path = Path(path) if path else DEFAULT_KEYMAP_PATH
        with open(path) as f:
            data = json.load(f)
        return cls(
            gameplay=data.get("gameplay", {}),
            hotbar=data.get("hotbar", {}),
            map=data.get("map", {}),
        )

    def save(self, path: str | Path) -> None:
        data = {"gameplay": self.gameplay, "hotbar": self.hotbar, "map": self.map}
        with open(path, "w") as f:
            json.dump(data, f, indent=4)

    def get_hotbar_key(self, slot: int) -> str | None:
        return self.hotbar.get(str(slot + 1))

    def get_gameplay_key(self, action: str) -> str | None:
        return self.gameplay.get(action)
