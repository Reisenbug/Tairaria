from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DamageInfo:
    took_damage: bool = False
    damage_amount: int = 0
    hp_trend: str = "stable"
    danger_level: str = "safe"


class DamageDetector:
    def __init__(self) -> None:
        self._prev_hp: int | None = None
        self._last_damage_time: float = 0.0
        self._history: list[int] = []

    def update(self, current_hp: int, max_hp: int, timestamp: float) -> DamageInfo:
        took_damage = False
        damage_amount = 0

        if self._prev_hp is not None and current_hp < self._prev_hp:
            took_damage = True
            damage_amount = self._prev_hp - current_hp
            self._last_damage_time = timestamp

        self._history.append(current_hp)
        if len(self._history) > 15:
            self._history = self._history[-15:]

        hp_trend = self._compute_trend()
        danger_level = self._compute_danger(current_hp, max_hp, timestamp)

        self._prev_hp = current_hp
        return DamageInfo(
            took_damage=took_damage,
            damage_amount=damage_amount,
            hp_trend=hp_trend,
            danger_level=danger_level,
        )

    def _compute_trend(self) -> str:
        if len(self._history) < 3:
            return "stable"
        recent = self._history[-3:]
        if recent[-1] < recent[0]:
            return "decreasing"
        if recent[-1] > recent[0]:
            return "recovering"
        return "stable"

    def _compute_danger(self, hp: int, max_hp: int, now: float) -> str:
        if max_hp <= 0:
            return "safe"
        ratio = hp / max_hp
        time_since_damage = now - self._last_damage_time

        if ratio < 0.3:
            return "critical"
        if ratio < 0.6 or time_since_damage < 2.0:
            return "warning"
        if time_since_damage < 3.0:
            return "warning"
        return "safe"

    def reset(self) -> None:
        self._prev_hp = None
        self._last_damage_time = 0.0
        self._history.clear()
