from __future__ import annotations

from terraria_agent.geometry import player_center_world
from terraria_agent.models.game_state import GameState

_TILE = 16.0


def _rel(entity_pos: tuple[float, float], pcx: float, pcy: float) -> tuple[int, int]:
    dx = round((entity_pos[0] - pcx) / _TILE)
    dy = round((entity_pos[1] - pcy) / _TILE)
    return dx, dy


def serialize(state: GameState) -> str:
    p = state.player
    pcx, pcy = player_center_world(p)
    lines: list[str] = []

    lines.append(f"hp={p.hp}/{p.max_hp} vel=({p.velocity[0]:.1f},{p.velocity[1]:.1f}) facing={p.direction}")
    lines.append(f"biome={state.biome} danger={p.danger_level} hp_trend={p.hp_trend}")

    if p.buffs:
        lines.append(f"buffs={','.join(p.buffs)}")

    terrain = state.terrain_scan
    if terrain:
        lines.append(f"terrain_ahead={terrain.terrain_type.value} dist={terrain.distance_tiles} size={terrain.depth_or_height}")

    hotbar_items = [f"{i}:{name}" for i, name in enumerate(state.hotbar) if name]
    lines.append(f"hotbar=[{', '.join(hotbar_items)}] selected={p.selected_slot}")
    lines.append(f"equipped={state.equipped}")

    if state.enemies:
        close = sorted(state.enemies, key=lambda e: e.distance)[:5]
        parts = []
        for e in close:
            dx, dy = _rel(e.pos, pcx, pcy)
            parts.append(f"{e.type}(hp={e.hp}/{e.max_hp},rel={dx:+d},{dy:+d},threat={e.threat.value})")
        lines.append(f"enemies=[{', '.join(parts)}]")

    if state.dropped_items:
        close_drops = sorted(state.dropped_items, key=lambda d: d.distance)[:5]
        parts = []
        for d in close_drops:
            dx, dy = _rel(d.pos, pcx, pcy)
            parts.append(f"{d.name}x{d.stack}(rel={dx:+d},{dy:+d})")
        lines.append(f"drops=[{', '.join(parts)}]")

    if state.objects:
        close_objs = sorted(state.objects, key=lambda o: o.distance)[:5]
        parts = []
        for o in close_objs:
            dx, dy = _rel(o.pos, pcx, pcy)
            parts.append(f"{o.type}(rel={dx:+d},{dy:+d})")
        lines.append(f"objects=[{', '.join(parts)}]")

    inv_summary = {k: v for k, v in state.inventory.items() if v > 0}
    if inv_summary:
        lines.append(f"inventory={inv_summary}")

    return "\n".join(lines)
