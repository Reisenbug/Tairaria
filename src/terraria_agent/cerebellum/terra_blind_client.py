from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Optional

from terraria_agent.cerebellum.damage_detector import DamageDetector
from terraria_agent.models.game_state import GameState, Player


_DEFAULT_URL = "http://127.0.0.1:17878/state"
_TIMEOUT_SEC = 0.1


class TerraBlindClient:
    def __init__(self, url: str = _DEFAULT_URL, timeout: float = _TIMEOUT_SEC) -> None:
        self._url = url
        self._timeout = timeout
        self._damage = DamageDetector()
        self._last_error_kind: str | None = None
        self._last_success_ts: float = 0.0

    def detect(self, frame) -> GameState:
        try:
            with urllib.request.urlopen(self._url, timeout=self._timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            self._note_error(f"urlerror:{type(e.reason).__name__}")
            return self._empty_state()
        except (TimeoutError, ConnectionError) as e:
            self._note_error(f"conn:{type(e).__name__}")
            return self._empty_state()
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self._note_error(f"parse:{type(e).__name__}")
            return self._empty_state()

        self._last_success_ts = time.time()
        self._last_error_kind = None
        return self._build_game_state(payload)

    def _build_game_state(self, payload: dict) -> GameState:
        p = payload.get("player", {})
        eq = payload.get("equipment", {})
        buffs_raw = payload.get("buffs", [])

        hp = int(p.get("hp", 0))
        max_hp = max(int(p.get("max_hp", 1)), 1)
        damage = self._damage.update(hp, max_hp, time.time())

        pos = p.get("pos", {})
        vel = p.get("vel", {})

        hotbar_raw = eq.get("hotbar", [])
        hotbar: list[Optional[str]] = [None] * 10
        for i, slot in enumerate(hotbar_raw[:10]):
            if not isinstance(slot, dict):
                continue
            name = slot.get("name", "")
            if name and int(slot.get("id", 0)) != 0:
                hotbar[i] = name

        held = eq.get("held_item", {}) or {}
        equipped = held.get("name") or "none"

        player = Player(
            hp=hp,
            max_hp=max_hp,
            mana=int(p.get("mana", 0)),
            max_mana=int(p.get("max_mana", 0)),
            pos=(float(pos.get("x", 0.0)), float(pos.get("y", 0.0))),
            velocity=(float(vel.get("x", 0.0)), float(vel.get("y", 0.0))),
            direction=str(p.get("direction", "right")),
            buffs=[str(b.get("name", "")) for b in buffs_raw if isinstance(b, dict)],
            took_damage=damage.took_damage,
            damage_amount=damage.damage_amount,
            danger_level=damage.danger_level,
            hp_trend=damage.hp_trend,
            selected_slot=int(eq.get("selected_slot", 0)),
            inventory_open=False,
        )
        return GameState(player=player, hotbar=hotbar, equipped=equipped)

    def _empty_state(self) -> GameState:
        return GameState(player=Player(hp=0, max_hp=1, pos=(0.0, 0.0)))

    def _note_error(self, kind: str) -> None:
        if self._last_error_kind != kind:
            self._last_error_kind = kind

    def reset(self) -> None:
        self._damage.reset()
