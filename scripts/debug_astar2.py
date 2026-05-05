import sys, os, time, json, urllib.request, heapq, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dataclasses import dataclass, field
from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient, scan_skyline, scan_standable

perception = TerraBlindClient()
_BASE = "http://127.0.0.1:17878"
direction = "left"
sign = 1 if direction == "right" else -1
_GOAL_RANGE = 40


def _post(path, data):
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(_BASE + path, data=body, method="POST")
        urllib.request.urlopen(req, timeout=1)
    except Exception:
        pass


@dataclass(order=True)
class _Node:
    f: float
    wx: int = field(compare=False)
    wy: int = field(compare=False)


def _solid(tw, wx, wy):
    t = tw.tile_at(wx, wy)
    return t is not None and t.solid and not t.platform


def astar2(state, sign):
    tw = state.tile_window
    if tw is None or not tw.rows:
        return None

    p = state.player
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    feet_y = int((p.pos[1] + p.height) / 16.0)

    start = (pcx, feet_y)

    skyline = scan_skyline(tw)
    goal = None
    for r in range(_GOAL_RANGE, 0, -1):
        gx = pcx + sign * r
        if gx in skyline:
            goal = (gx, skyline[gx] - 1)
            break
    if goal is None:
        for r in range(1, _GOAL_RANGE + 1):
            gx = pcx - sign * r
            if gx in skyline:
                goal = (gx, skyline[gx] - 1)
                break
    if goal is None:
        print(f"[astar2] no goal")
        return []

    goal_wx, goal_wy = goal

    ox, oy = tw.origin
    x_min, x_max = ox, ox + tw.width - 1

    standable = scan_standable(tw)
    by_col = {}
    for (wx, wy) in standable:
        by_col.setdefault(wx, []).append(wy)

    g = {start: 0.0}
    prev = {start: None}
    heap = [_Node(float(abs(goal_wx - pcx) + abs(goal_wy - feet_y)), pcx, feet_y)]

    while heap:
        node = heapq.heappop(heap)
        cx, cy = node.wx, node.wy

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
        for step_sign in (sign, -sign):
            # find next column with standable nodes, up to GOAL_RANGE away
            for dist in range(1, _GOAL_RANGE + 1):
                nx = cx + step_sign * dist
                if nx < x_min or nx > x_max:
                    break
                if nx not in by_col:
                    continue
                for ny in by_col[nx]:
                    if dist > 1 and abs(ny - cy) > dist:
                        continue
                    fall = ny > cy
                    if fall:
                        blocked = sum(1 for y in range(cy, ny) if _solid(tw, nx, y))
                    else:
                        blocked = sum(1 for y in range(ny, cy) if _solid(tw, cx, y))
                    drop = max(0, ny - cy)
                    rise = max(0, cy - ny)
                    if fall:
                        if drop <= 3:
                            move_cost = 0
                        elif drop <= 7:
                            move_cost = (drop - 3) * 1
                        else:
                            move_cost = (drop - 3) * 3
                    else:
                        move_cost = max(0, rise - 7) * 4
                    bridge_cost = (dist - 1) * 3
                    ng = cur_g + (0 if dist > 1 else move_cost) + bridge_cost + blocked * 1000
                    npos = (nx, ny)
                    if ng < g.get(npos, math.inf):
                        g[npos] = ng
                        if dist > 1:
                            action = "bridge"
                            for i, bx in enumerate(range(cx + step_sign, nx, step_sign)):
                                t = (i + 1) / dist
                                by = int(cy + (ny - cy) * t)
                                by_col.setdefault(bx, [])
                                if by not in by_col[bx]:
                                    by_col[bx].append(by)
                        elif rise > 7:
                            action = "pillar"
                        elif fall:
                            action = "fall"
                        else:
                            action = "move"
                        prev[npos] = ((cx, cy), action)
                        h = abs(goal_wx - nx) + abs(goal_wy - ny)
                        heapq.heappush(heap, _Node(ng + h, nx, ny))
                if any(ng < 1000 for ng in [g.get((nx, ny), math.inf) for ny in by_col.get(nx, [])]):
                    break

    candidates = [(wx, wy) for (wx, wy) in g if sign * (wx - pcx) > 0]
    if not candidates:
        candidates = [(wx, wy) for (wx, wy) in g if (wx, wy) != start]
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
    print(f"[astar2] fallback {start}→{fallback} len={len(path)} cost={total_cost:.1f} (goal was {goal})")
    return path, total_cost


while True:
    state = perception.detect(frame=None)
    if state.player.hp == 0:
        time.sleep(0.2)
        continue
    tw = state.tile_window
    if tw is None:
        time.sleep(0.2)
        continue

    p = state.player
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    feet_y = int((p.pos[1] + p.height) / 16.0)

    result = astar2(state, sign)

    if not result:
        print(f"[vis] no path at ({pcx},{feet_y})")
        time.sleep(2.0)
        continue
    path, total_cost = result
    if not path:
        time.sleep(2.0)
        continue
    else:
        print(f"[path] ({pcx},{feet_y})→({path[-1][0]},{path[-1][1]}) len={len(path)} cost={total_cost:.1f}")
        tiles = [{"wx": pcx, "wy": feet_y, "r": 255, "g": 255, "b": 255}]
        prev_wx, prev_y = pcx, feet_y
        for wx, wy, action in path:
            if action == "bridge":
                adx = abs(wx - prev_wx)
                dy_per_step = (wy - prev_y) / max(adx, 1)
                for i, bx in enumerate(range(prev_wx + sign, wx, sign)):
                    by = int(prev_y + dy_per_step * (i + 1))
                    tiles.append({"wx": bx, "wy": by, "r": 180, "g": 0, "b": 255})
            node_color = (255, 80, 80) if action == "pillar" else (100, 220, 255)
            tiles.append({"wx": wx, "wy": wy, "r": node_color[0], "g": node_color[1], "b": node_color[2]})
            if wy > prev_y:
                for y in range(prev_y, wy):
                    tiles.append({"wx": wx, "wy": y, "r": 255, "g": 140, "b": 0})
            elif wy < prev_y:
                rise = prev_y - wy
                for y in range(wy, prev_y):
                    c = (255, 80, 80) if rise > 7 else (100, 255, 100)
                    tiles.append({"wx": wx - sign, "wy": y, "r": c[0], "g": c[1], "b": c[2]})
            prev_wx, prev_y = wx, wy
        _post("/path_vis_tiles", tiles)
        _post("/debug_labels", [{"wx": path[-1][0], "wy": path[-1][1],
                                  "text": f"goal len={len(path)} cost={total_cost:.1f}",
                                  "r": 255, "g": 200, "b": 0}])

    time.sleep(2.0)
