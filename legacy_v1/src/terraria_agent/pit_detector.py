from __future__ import annotations

from dataclasses import dataclass
from terraria_agent.models.game_state import GameState
from terraria_agent.cerebellum.terra_blind_client import scan_surface, _jump_peak_tiles, _jump_envelope

_PIT_DROP = 3
_CAVE_HEADROOM = 3
_SCAN_COLS = 25


@dataclass
class Obstacle:
    kind: str
    dist: int
    width: int
    delta: int


def detect(state: GameState) -> Obstacle | None:
    tw = state.tile_window
    if tw is None or not tw.rows:
        return None

    p = state.player
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    feet_y = int((p.pos[1] + p.height) / 16.0)
    sign = 1 if p.direction == "right" else -1

    surface = scan_surface(tw)
    base_y = surface.get(pcx, feet_y)
    jump_width = len([dy for dy in _jump_envelope(state.movement, max_cols=30) if dy <= 0])

    cols = [surface.get(pcx + sign * i) for i in range(1, _SCAN_COLS + 1)]

    pit_start = None
    pit_width = 0
    pit_depth = 0
    for i, sy in enumerate(cols):
        drop = (sy - base_y) if sy is not None else _SCAN_COLS
        if drop > _PIT_DROP:
            if pit_start is None:
                pit_start = i + 1
            pit_width += 1
            pit_depth = max(pit_depth, drop)
        else:
            if pit_start is not None:
                if pit_width > jump_width:
                    return Obstacle(kind="pit", dist=pit_start, width=pit_width, delta=pit_depth)
                pit_start = None
                pit_width = 0
                pit_depth = 0
    if pit_start is not None and pit_width > jump_width:
        return Obstacle(kind="pit", dist=pit_start, width=pit_width, delta=pit_depth)

    for i, sy in enumerate(cols):
        if sy is None:
            continue
        headroom = feet_y - sy
        if base_y - sy > 0 and headroom < _CAVE_HEADROOM:
            return Obstacle(kind="cave", dist=i + 1, width=1, delta=base_y - sy)

    return None
