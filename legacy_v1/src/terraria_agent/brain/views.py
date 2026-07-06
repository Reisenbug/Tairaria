"""
Scenario-based state views for the Tactician.

Instead of dumping the whole game state to the LLM every call, pick fields
relevant to the current situation. Output JSON schema is static (lives in
the system prompt); these views only carry data.
"""
from __future__ import annotations

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


def _tile_grid_text(gs: GameState, back: int = 3, forward: int = 12,
                    up: int = 5, down: int = 4) -> str | None:
    """ASCII local grid anchored at player feet. P=player, #=solid,
    ~=water, !=lava, .=air, ?=unknown. Columns flipped when facing left
    so forward is always rightward in the rendered grid."""
    tw = gs.tile_window
    if not tw or not tw.rows:
        return None
    p = gs.player
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    feet_y = int((p.pos[1] + p.height) / 16.0)
    head_y = int(p.pos[1] / 16.0)
    sign = 1 if p.direction == "right" else -1

    lines: list[str] = []
    for dy in range(-up, down + 1):
        wy = feet_y + dy
        row = []
        for dx in range(-back, forward + 1):
            wx = pcx + sign * dx
            if dx == 0 and head_y <= wy <= feet_y:
                row.append("P")
                continue
            t = tw.tile_at(wx, wy)
            if t is None:
                row.append("?")
            elif t.solid:
                row.append("#")
            elif t.lava:
                row.append("!")
            elif t.water:
                row.append("~")
            else:
                row.append(".")
        lines.append("".join(row))
    width = back + forward + 1
    header = f"grid({width}x{up + down + 1} P=feet col{back}, rows above→below, cols back→forward):"
    return header + "\n" + "\n".join(lines)


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


def _nearby_targets(gs: GameState, max_distance: float = 20.0, limit: int = 6) -> list[dict]:
    items = [
        {"type": o.type, "tile": list(o.tile_pos), "d": round(o.distance, 1)}
        for o in gs.objects
        if o.type in ("tree", "chest") and o.distance <= max_distance
    ]
    items.sort(key=lambda r: r["d"])
    return items[:limit]


def build_view(gs: GameState, events: list[BrainEvent], goal: str, goal_achieved: bool) -> dict:
    scenario = _pick_scenario(gs, events)
    view = _base(gs)
    view["scenario"] = scenario
    view["goal"] = goal
    if goal_achieved:
        view["goal_achieved"] = True

    if scenario == "walking":
        grid = _tile_grid_text(gs, back=3, forward=12, up=5, down=4)
        if grid:
            view["grid_ahead"] = grid
        view["on_ground"] = gs.player.velocity[1] == 0.0
        view["have"] = sorted(
            {s.category for s in gs.inventory_slots if not s.is_empty and s.category != "misc"}
        )
        targets = _nearby_targets(gs)
        if targets:
            view["targets"] = targets

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
        grid = _tile_grid_text(gs, back=4, forward=16, up=6, down=6)
        if grid:
            view["grid_ahead"] = grid
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
