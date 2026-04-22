from __future__ import annotations

from terraria_agent.models.game_state import GameState


def serialize(state: GameState) -> str:
    p = state.player
    lines: list[str] = []

    lines.append(f"hp={p.hp}/{p.max_hp} pos=({p.pos[0]:.0f},{p.pos[1]:.0f}) vel=({p.velocity[0]:.1f},{p.velocity[1]:.1f}) facing={p.direction}")
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
        parts = [f"{e.type}(hp={e.hp}/{e.max_hp},dist={e.distance:.1f},threat={e.threat.value})" for e in close]
        lines.append(f"enemies=[{', '.join(parts)}]")

    if state.dropped_items:
        close_drops = sorted(state.dropped_items, key=lambda d: d.distance)[:5]
        parts = [f"{d.name}x{d.stack}(dist={d.distance:.1f})" for d in close_drops]
        lines.append(f"drops=[{', '.join(parts)}]")

    if state.objects:
        close_objs = sorted(state.objects, key=lambda o: o.distance)[:5]
        parts = [f"{o.type}(dist={o.distance:.1f})" for o in close_objs]
        lines.append(f"objects=[{', '.join(parts)}]")

    inv_summary = {k: v for k, v in state.inventory.items() if v > 0}
    if inv_summary:
        lines.append(f"inventory={inv_summary}")

    return "\n".join(lines)
