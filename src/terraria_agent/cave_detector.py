from __future__ import annotations

from terraria_agent.models.game_state import GameState, TileWindow

_CLOUD_TYPES = {189, 196}
_THICK_THRESHOLD = 20


def _has_overhead(tw: TileWindow, pcx: int, head_y: int) -> bool:
    for dy in range(1, 16):
        t = tw.tile_at(pcx, head_y - dy)
        if t is None:
            continue
        if t.type in _CLOUD_TYPES:
            return False
        if t.solid:
            return True
    return False


def _roof_thickness(tw: TileWindow, cx: int, head_y: int) -> int:
    first_dy = None
    for dy in range(1, 30):
        t = tw.tile_at(cx, head_y - dy)
        if t is None:
            continue
        if t.type in _CLOUD_TYPES:
            return 0
        if t.solid:
            first_dy = dy
            break
    if first_dy is None:
        return 0
    count = 0
    for dy in range(first_dy, first_dy + 20):
        t = tw.tile_at(cx, head_y - dy)
        if t is not None and t.solid and t.type not in _CLOUD_TYPES:
            count += 1
        else:
            break
    return count


def _find_overhead_edge(tw: TileWindow, pcx: int, head_y: int, cave_sign: int) -> int:
    scan_sign = -cave_sign
    for i in range(0, 20):
        cx = pcx + scan_sign * i
        has = False
        for dy in range(1, 16):
            t = tw.tile_at(cx, head_y - dy)
            if t is None:
                continue
            if t.type in _CLOUD_TYPES:
                break
            if t.solid:
                has = True
                break
        if not has:
            return i
    return 0


def detect(state: GameState) -> tuple[bool, str, int, int] | None:
    tw = state.tile_window
    if tw is None or not tw.rows:
        return None

    p = state.player
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    head_y = int(p.pos[1] / 16.0)

    if not _has_overhead(tw, pcx, head_y):
        return None

    direction = p.direction
    sign = 1 if direction == "right" else -1
    thicknesses = [_roof_thickness(tw, pcx + sign * i, head_y) for i in range(1, 16)]
    if max(thicknesses) >= _THICK_THRESHOLD:
        edge_i = _find_overhead_edge(tw, pcx, head_y, sign)
        walk_back = max(1, edge_i + 2)
        roof_dy = next((dy for dy in range(1, 16)
                       if (t := tw.tile_at(pcx, head_y - dy)) and t.solid and t.type not in _CLOUD_TYPES), 7)
        rise_tiles = roof_dy - 7
        if rise_tiles >= 2:
            return True, direction, walk_back, rise_tiles

    return None
