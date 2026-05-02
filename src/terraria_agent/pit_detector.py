from __future__ import annotations

from terraria_agent.models.game_state import GameState, TileWindow
from terraria_agent.cerebellum.terra_blind_client import _jump_peak_tiles, _jump_envelope

_SCAN_COLS = 25
_SURFACE_SCAN_DOWN = 20


def _surface_y(tw: TileWindow, cx: int, from_y: int) -> int | None:
    for dy in range(_SURFACE_SCAN_DOWN):
        t = tw.tile_at(cx, from_y + dy)
        if t is not None and (t.solid or t.platform):
            return from_y + dy
    return None


def detect(state: GameState) -> tuple[str, int, int, int] | None:
    """
    Returns (direction, pit_start_col, pit_width, pit_depth) if an unbridgeable pit
    is ahead, else None.
    """
    tw = state.tile_window
    if tw is None or not tw.rows:
        return None

    p = state.player
    mv = state.movement
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    feet_y = int((p.pos[1] + p.height) / 16.0)
    head_y = int(p.pos[1] / 16.0)

    jump_height = _jump_peak_tiles(mv)
    jump_width = len([dy for dy in _jump_envelope(mv, max_cols=30) if dy <= 0])

    sign = 1 if p.direction == "right" else -1

    surface = []
    for i in range(1, _SCAN_COLS + 1):
        cx = pcx + sign * i
        sy = _surface_y(tw, cx, feet_y - 1)
        surface.append(sy)

    pit_start = None
    pit_width = 0
    pit_depth = 0

    for i, sy in enumerate(surface):
        drop = (sy - feet_y) if sy is not None else _SURFACE_SCAN_DOWN
        is_pit_col = drop > 2

        if is_pit_col:
            if pit_start is None:
                pit_start = i + 1
            pit_width += 1
            pit_depth = max(pit_depth, drop)
        else:
            if pit_start is not None:
                if pit_width > jump_width:
                    return (p.direction, pit_start, pit_width, pit_depth)
                pit_start = None
                pit_width = 0
                pit_depth = 0

    if pit_start is not None and pit_width > jump_width:
        return (p.direction, pit_start, pit_width, pit_depth)

    return None
