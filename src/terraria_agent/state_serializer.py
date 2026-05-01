from __future__ import annotations

from terraria_agent.geometry import player_center_world
from terraria_agent.models.game_state import GameState

_TILE = 16.0


def _rel(entity_pos: tuple[float, float], pcx: float, pcy: float) -> tuple[int, int]:
    dx = round((entity_pos[0] - pcx) / _TILE)
    dy = round((entity_pos[1] - pcy) / _TILE)
    return dx, dy


def serialize(state: GameState, focus: str = "deadline") -> str:
    p = state.player
    pcx, pcy = player_center_world(p)
    lines: list[str] = []

    # 基础层：所有触发都包含
    lines.append(f"hp={p.hp}/{p.max_hp} vel=({p.velocity[0]:.1f},{p.velocity[1]:.1f}) facing={p.direction}")
    lines.append(f"biome={state.biome} danger={p.danger_level} hp_trend={p.hp_trend}")
    hotbar_items = [f"{i}:{name}" for i, name in enumerate(state.hotbar) if name]
    lines.append(f"hotbar=[{', '.join(hotbar_items)}] selected={p.selected_slot}")

    want_tiles   = focus in ("deadline", "生物群系切换")
    want_terrain = focus in ("deadline", "卡住", "地形突变_pit")
    want_enemies = focus in ("deadline", "血量骤降")
    want_drops   = focus in ("deadline",)
    want_objects = focus in ("deadline", "发现箱子")
    want_inv     = focus in ("deadline", "发现新物品", "掉落_武器", "掉落_水果")
    want_craft   = focus in ("deadline", "发现新物品", "掉落_武器", "掉落_水果")
    want_buffs   = focus in ("血量骤降",)

    if want_buffs and p.buffs:
        lines.append(f"buffs={','.join(p.buffs)}")

    if want_terrain:
        terrain = state.terrain_scan
        if terrain:
            lines.append(f"terrain_ahead={terrain.terrain_type.value} dist={terrain.distance_tiles} size={terrain.depth_or_height}")

    if want_enemies and state.enemies:
        close = sorted(state.enemies, key=lambda e: e.distance)[:5]
        parts = []
        for e in close:
            dx, dy = _rel(e.pos, pcx, pcy)
            parts.append(f"{e.type}(hp={e.hp}/{e.max_hp},rel={dx:+d},{dy:+d},threat={e.threat.value})")
        lines.append(f"enemies=[{', '.join(parts)}]")

    if want_drops and state.dropped_items:
        close_drops = sorted(state.dropped_items, key=lambda d: d.distance)[:5]
        parts = []
        for d in close_drops:
            dx, dy = _rel(d.pos, pcx, pcy)
            parts.append(f"{d.name}x{d.stack}(rel={dx:+d},{dy:+d})")
        lines.append(f"drops=[{', '.join(parts)}]")

    if want_objects and state.objects:
        close_objs = sorted(state.objects, key=lambda o: o.distance)[:5]
        parts = []
        for o in close_objs:
            dx, dy = _rel(o.pos, pcx, pcy)
            parts.append(f"{o.type}(rel={dx:+d},{dy:+d})")
        lines.append(f"objects=[{', '.join(parts)}]")

    if want_tiles and state.detected_tiles:
        parts = [f"{t.name}(rel={t.rel_x:+d},{t.rel_y:+d})" for t in state.detected_tiles]
        lines.append(f"detected_tiles=[{', '.join(parts)}]")

    if want_inv:
        inv_summary = {k: v for k, v in state.inventory.items() if v > 0}
        if inv_summary:
            lines.append(f"inventory={inv_summary}")

    if want_craft:
        if state.nearby_stations:
            lines.append(f"nearby_stations={state.nearby_stations}")
        if state.available_recipes:
            parts = []
            for r in state.available_recipes:
                ings = "+".join(f"{n}x{c}" for n, c in r.ingredients)
                parts.append(f"{r.item_name}(id={r.item_id},x{r.result_stack},需要:{ings})")
            lines.append(f"可制作=[{', '.join(parts)}]")

    return "\n".join(lines)


def serialize_macro(state: GameState, goal: str = "", visited_biomes: list[str] | None = None) -> str:
    p = state.player
    lines: list[str] = []

    lines.append(f"hp={p.hp}/{p.max_hp} hp_trend={p.hp_trend} danger={p.danger_level}")
    lines.append(f"biome={state.biome}")
    if visited_biomes:
        lines.append(f"visited_biomes={','.join(visited_biomes)}")

    inv_summary = {k: v for k, v in state.inventory.items() if v > 0}
    if inv_summary:
        lines.append(f"inventory={inv_summary}")

    categories = list({s.category for s in state.inventory_slots if s.category and s.name})
    if categories:
        lines.append(f"have_categories={','.join(sorted(categories))}")

    if goal:
        lines.append(f"current_goal={goal}")

    return "\n".join(lines)
