from __future__ import annotations

from dataclasses import dataclass
from terraria_agent.models.game_state import GameState
from terraria_agent.cerebellum.terra_blind_client import scan_surface

_EDGE_THRESHOLD = 6
_WALKABLE_RISE = 1
_JUMPABLE_RISE = 6
_FORWARD_SCAN = 20
_OPPOSITE_SCAN = 40


@dataclass
class NavAction:
    action: str
    dist: int
    delta: int


def _find_edges(surface, tw) -> set[int]:
    edges = set()
    prev_wx = None
    for rx in range(tw.width):
        wx = tw.origin[0] + rx
        sy = surface.get(wx)
        if prev_wx is not None:
            prev_sy = surface.get(prev_wx)
            if sy is not None and prev_sy is not None and abs(sy - prev_sy) > _EDGE_THRESHOLD:
                edges.add(prev_wx)
                edges.add(wx)
        prev_wx = wx
    return edges


def next_action(state: GameState) -> NavAction | None:
    tw = state.tile_window
    if tw is None or not tw.rows:
        return None

    p = state.player
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    feet_y = int((p.pos[1] + p.height) / 16.0)
    sign = 1 if p.direction == "right" else -1

    surface = scan_surface(tw)
    base_y = surface.get(pcx, feet_y)
    edges = _find_edges(surface, tw)

    for i in range(1, _FORWARD_SCAN + 1):
        wx = pcx + sign * i
        if wx not in edges:
            continue
        left_sy = surface.get(wx, base_y)

        opposite = None
        for j in range(1, _OPPOSITE_SCAN + 1):
            owx = wx + sign * j
            if owx not in edges:
                continue
            osy = surface.get(owx)
            if osy is not None and osy <= left_sy + 2:
                opposite = (owx, osy)
                break

        if opposite is None:
            for j in range(1, _OPPOSITE_SCAN + 1):
                owx = wx + sign * j
                if owx not in edges:
                    continue
                osy = surface.get(owx)
                if osy is not None:
                    opposite = (owx, osy)
                    break

        if opposite is None:
            return NavAction(action="bridge", dist=i, delta=0)

        owx, osy = opposite
        rise = base_y - osy
        if rise > _JUMPABLE_RISE:
            return NavAction(action="bridge", dist=owx - pcx, delta=rise)
        if rise > _WALKABLE_RISE:
            return NavAction(action="jump", dist=owx - pcx, delta=rise)
        return NavAction(action="walk", dist=owx - pcx, delta=rise)

    return NavAction(action="walk", dist=_FORWARD_SCAN, delta=0)
