from __future__ import annotations

import heapq
import json
import math
import urllib.request
from dataclasses import dataclass, field

from terraria_agent.cerebellum.terra_blind_client import scan_skyline, _jump_envelope
from terraria_agent.models.game_state import MovementInfo

_GROUND_MOVEMENT = MovementInfo()
_GOAL_RANGE = 40
_MAX_BRIDGE = 15
_MAX_JUMP_COLS = 8
_BASE = "http://127.0.0.1:17878"


def fetch_jump_envelope(max_cols: int = _MAX_BRIDGE + 1) -> list[int]:
    try:
        resp = urllib.request.urlopen(_BASE + "/jump_envelope", timeout=1)
        data = json.loads(resp.read())
        env = data["envelope"]
        if len(env) < max_cols:
            env += [env[-1]] * (max_cols - len(env))
        return env[:max_cols]
    except Exception:
        return _jump_envelope(_GROUND_MOVEMENT, max_cols=max_cols)


@dataclass(order=True)
class _Node:
    f: float
    wx: int = field(compare=False)
    wy: int = field(compare=False)


def _solid(tw, wx, wy):
    t = tw.tile_at(wx, wy)
    return t is not None and t.solid and not t.platform


def _standable(tw, wx, wy):
    return not _solid(tw, wx, wy) and _solid(tw, wx, wy + 1)


def _project_down(tw, wx, wy, max_drop=15):
    for dy in range(max_drop):
        if _standable(tw, wx, wy + dy):
            return wy + dy
    return None


def _dist_to_ground(tw, wx, wy, max_depth=20):
    for d in range(max_depth):
        if _solid(tw, wx, wy + d):
            return d
    return max_depth


def _bridge_ground_penalty(dtg):
    if dtg >= 8:
        return 0
    return (8 - dtg) * 2


def _step_cost(dy):
    if dy > 0:
        return dy * 0.5
    rise = -dy
    if rise <= 7:
        return rise
    return 7 + (rise - 7) ** 2


def astar2(state, sign):
    tw = state.tile_window
    if tw is None or not tw.rows:
        return None

    p = state.player
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    feet_y = int((p.pos[1] + p.height) / 16.0)

    envelope = fetch_jump_envelope(max_cols=_MAX_JUMP_COLS + 1)
    start = (pcx, feet_y)

    skyline = scan_skyline(tw)
    target_x = pcx + sign * _GOAL_RANGE
    candidates = [(gx, skyline[gx] - 1) for gx in skyline if sign * (gx - pcx) > 0]
    if not candidates:
        candidates = [(gx, skyline[gx] - 1) for gx in skyline]
    goal = min(candidates, key=lambda p: abs(p[0] - target_x)) if candidates else None
    if goal is None:
        print("[astar2] no goal")
        return []

    goal_wx, goal_wy = goal

    ox, oy = tw.origin
    x_min = max(ox, pcx - _GOAL_RANGE)
    x_max = min(ox + tw.width - 1, pcx + _GOAL_RANGE)
    y_min = max(oy, feet_y - 20)
    y_max = min(oy + tw.height - 1, feet_y + 15)

    g = {start: 0.0}
    prev = {start: None}
    visited = set()
    bridge_nodes = set()
    heap = [_Node(float(abs(goal_wx - pcx) + abs(goal_wy - feet_y)), pcx, feet_y)]

    while heap:
        node = heapq.heappop(heap)
        cx, cy = node.wx, node.wy

        if (cx, cy) in visited:
            continue
        visited.add((cx, cy))

        if cx == goal_wx and cy == goal_wy:
            path = []
            pos = (cx, cy)
            while prev[pos] is not None:
                ppos, action = prev[pos]
                path.append((pos[0], pos[1], action))
                pos = ppos
            path.reverse()
            return path, g.get((cx, cy), 0)

        cur_g = g.get((cx, cy), math.inf)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = cx + dx, cy + dy
            if nx < x_min or nx > x_max or ny < y_min or ny > y_max:
                continue
            if _solid(tw, nx, ny):
                continue
            if dy == -1 and dx == 0:
                continue
            if dy == -1 and not _solid(tw, nx, ny + 1):
                continue
            dtg = _dist_to_ground(tw, nx, ny) if dx != 0 else 0
            if dx != 0 and dtg >= 2:
                continue
            if dy == 1:
                cost = 0.5
            else:
                cost = 1 + dtg
            ng = cur_g + cost
            npos = (nx, ny)
            if ng < g.get(npos, math.inf):
                g[npos] = ng
                action = "fall" if dy == 1 else "move"
                prev[npos] = ((cx, cy), action)
                h = abs(goal_wx - nx) + abs(goal_wy - ny)
                heapq.heappush(heap, _Node(ng + h, nx, ny))

        if (_standable(tw, cx, cy) or (cx, cy) in bridge_nodes) and \
                not _solid(tw, cx, cy - 1) and not _solid(tw, cx, cy - 2):
            for js in (1, -1):
                for col in range(1, len(envelope)):
                    nx = cx + js * col
                    if nx < x_min or nx > x_max:
                        break
                    arc_dy = envelope[col]
                    blocked = False
                    for i in range(1, col):
                        arc_y = cy + envelope[i]
                        bx = cx + js * i
                        if _solid(tw, bx, arc_y) or _solid(tw, bx, arc_y - 1):
                            blocked = True
                            break
                    if blocked:
                        break
                    for ny in range(cy + arc_dy, min(cy + arc_dy + 4, y_max + 1)):
                        if _standable(tw, nx, ny):
                            rise = cy - ny
                            rise_bonus = max(0, rise - 1) * 2
                            cost = 4 + col * 1.0 - rise_bonus
                            ng = cur_g + max(cost, 1.0)
                            npos = (nx, ny)
                            if ng < g.get(npos, math.inf):
                                g[npos] = ng
                                action = "jump"
                                prev[npos] = ((cx, cy), action)
                                h = abs(goal_wx - nx) + abs(goal_wy - ny)
                                heapq.heappush(heap, _Node(ng + h, nx, ny))
                            break

        if _standable(tw, cx, cy):
            for js in (sign,):
                min_dtg = 20
                for col in range(1, _MAX_BRIDGE + 1):
                    nx = cx + js * col
                    if nx < x_min or nx > x_max:
                        break
                    if _solid(tw, nx, cy):
                        break
                    if _solid(tw, nx, cy - 1) or _solid(tw, nx, cy - 2):
                        break
                    min_dtg = min(min_dtg, _dist_to_ground(tw, nx, cy))
                    if _standable(tw, nx, cy):
                        shallow_penalty = _bridge_ground_penalty(min_dtg)
                        cost = 4 + col * 2.0 + shallow_penalty
                        ng = cur_g + cost
                        npos = (nx, cy)
                        if ng < g.get(npos, math.inf):
                            g[npos] = ng
                            prev[npos] = ((cx, cy), "bridge")
                            h = abs(goal_wx - nx) + abs(goal_wy - cy)
                            heapq.heappush(heap, _Node(ng + h, nx, cy))

    candidates = [(wx, wy) for (wx, wy) in visited if sign * (wx - pcx) > 0 and _standable(tw, wx, wy)]
    if not candidates:
        candidates = [(wx, wy) for (wx, wy) in visited if (wx, wy) != start and _standable(tw, wx, wy)]
    if not candidates:
        return []
    fallback = max(candidates, key=lambda p: sign * p[0])
    path = []
    pos = fallback
    while prev[pos] is not None:
        ppos, action = prev[pos]
        path.append((pos[0], pos[1], action))
        pos = ppos
    path.reverse()
    total_cost = g.get(fallback, 0)
    print(f"[astar2] fallback →({fallback[0]},{fallback[1]}) len={len(path)} cost={total_cost:.1f} (goal was {goal})")
    return path, total_cost
