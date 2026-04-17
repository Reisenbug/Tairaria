"""
Scenario-based state views for the Tactician.

Instead of dumping the whole game state to the LLM every call, pick fields
relevant to the current situation. Output JSON schema is static (lives in
the system prompt); these views only carry data.
"""
from __future__ import annotations

from typing import Any

from terraria_agent.models.game_state import GameState
from terraria_agent.spinal_cord.context import BrainEvent


def _inventory_by_category(gs: GameState, categories: list[str] | None = None) -> dict:
    out: dict[str, list[str]] = {}
    for s in gs.inventory_slots:
        if s.is_empty:
            continue
        if categories is not None and s.category not in categories:
            continue
        out.setdefault(s.category, []).append(
            f"{s.name}×{s.stack}" if s.stack > 1 else s.name
        )
    return out


def _scan_ahead_text(gs: GameState, columns: int) -> str | None:
    tw = gs.tile_window
    if not tw or not tw.rows:
        return None
    p = gs.player
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    feet_y = int((p.pos[1] + p.height) / 16.0)
    sign = 1 if p.direction == "right" else -1

    lines = []
    for i in range(1, columns + 1):
        cx = pcx + sign * i
        rx = cx - tw.origin[0]
        solids: list[Any] = []
        for dy in range(-4, 8):
            wy = feet_y + dy
            ry = wy - tw.origin[1]
            if 0 <= ry < tw.height and 0 <= rx < tw.width:
                col = 0
                for run in tw.rows[ry]:
                    if rx < col + run.count:
                        if run.solid:
                            solids.append(dy)
                        elif run.lava:
                            solids.append(f"lava@{dy}")
                        elif run.water:
                            solids.append(f"water@{dy}")
                        break
                    col += run.count
        lines.append(f"+{i}:{solids}" if solids else f"+{i}:air")
    return " ".join(lines)


def _base(gs: GameState) -> dict:
    p = gs.player
    return {
        "hp": p.hp,
        "max_hp": p.max_hp,
        "pos": {"x": round(p.pos[0]), "y": round(p.pos[1])},
        "dir": p.direction,
        "biome": gs.biome,
    }


def _pick_scenario(gs: GameState, events: list[BrainEvent]) -> str:
    p = gs.player
    hp_pct = p.hp / max(p.max_hp, 1)
    if hp_pct < 0.35:
        return "low_hp"
    if gs.enemies:
        return "combat"
    for e in events:
        if e.type in ("stuck", "obstacle", "deep_pit"):
            return "terrain"
    return "walking"


def build_view(gs: GameState, events: list[BrainEvent], goal: str, goal_achieved: bool) -> dict:
    scenario = _pick_scenario(gs, events)
    view = _base(gs)
    view["scenario"] = scenario
    view["goal"] = goal
    if goal_achieved:
        view["goal_achieved"] = True

    if scenario == "walking":
        terrain = _scan_ahead_text(gs, columns=12)
        if terrain:
            view["terrain_ahead"] = terrain
        view["on_ground"] = gs.player.velocity[1] == 0.0
        view["have"] = sorted(
            {s.category for s in gs.inventory_slots if not s.is_empty and s.category != "misc"}
        )

    elif scenario == "combat":
        view["enemies"] = [
            {"n": e.type, "hp": e.hp, "d": round(e.distance, 1), "boss": e.boss}
            for e in gs.enemies[:5]
        ]
        view["weapons"] = _inventory_by_category(gs, ["weapon", "ammo"])
        view["buffs"] = list(gs.player.buffs)[:6]

    elif scenario == "low_hp":
        view["enemies"] = [
            {"n": e.type, "d": round(e.distance, 1)} for e in gs.enemies[:3]
        ]
        view["consumables"] = _inventory_by_category(gs, ["consumable"])
        view["buffs"] = list(gs.player.buffs)[:6]

    elif scenario == "terrain":
        terrain = _scan_ahead_text(gs, columns=16)
        if terrain:
            view["terrain_ahead"] = terrain
        view["movement"] = {
            "jump": gs.movement.jump_height,
            "speed": gs.movement.max_run_speed,
            "no_fall_dmg": gs.movement.no_fall_dmg,
        }
        view["have"] = sorted(
            {s.category for s in gs.inventory_slots if not s.is_empty and s.category != "misc"}
        )

    if events:
        view["events"] = [
            {"type": e.type, **e.details} for e in events[-5:]
        ]

    return view


def build_commander_view(
    gs: GameState,
    strategic_events: list[BrainEvent],
    recent_tactical_decisions: list[dict],
    goal: str,
    goal_achieved: bool,
) -> dict:
    """Strategic view: long-term state + strategic events + tactician's recent moves."""
    p = gs.player
    categories = sorted(
        {s.category for s in gs.inventory_slots if not s.is_empty and s.category != "misc"}
    )
    view = {
        "hp": p.hp,
        "max_hp": p.max_hp,
        "pos": {"x": round(p.pos[0]), "y": round(p.pos[1])},
        "biome": gs.biome,
        "goal": goal,
        "goal_achieved": goal_achieved,
        "have_categories": categories,
    }
    if recent_tactical_decisions:
        view["recent_tactical_decisions"] = recent_tactical_decisions[-5:]
    if strategic_events:
        view["strategic_events"] = [
            {"type": e.type, **e.details} for e in strategic_events[-10:]
        ]
    return view
