import sys, os, time, json, urllib.request, heapq, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dataclasses import dataclass, field
from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient, scan_skyline, scan_standable, _jump_envelope
from terraria_agent.models.game_state import MovementInfo
_GROUND_MOVEMENT = MovementInfo()

perception = TerraBlindClient()
_BASE = "http://127.0.0.1:17878"
direction = "left"
sign = 1 if direction == "right" else -1
_GOAL_RANGE = 40
_MAX_BRIDGE = 15


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


def _standable(tw, wx, wy):
    return not _solid(tw, wx, wy) and _solid(tw, wx, wy + 1)


def _project_down(tw, wx, wy, max_drop=15):
    for dy in range(max_drop):
        if _standable(tw, wx, wy + dy):
            return wy + dy
    return None


def _project_path(tw, raw_path, start, goal):
    segments = []
    cur_proj = _project_down(tw, start[0], start[1]) or start[1]
    cur_x = start[0]
    seg_actions = []

    for wx, wy, action in raw_path:
        py = _project_down(tw, wx, wy)
        if py is None:
            seg_actions.append(action)
            continue
        if wx != cur_x:
            segments.append((cur_x, cur_proj, wx, py, list(seg_actions)))
            cur_x, cur_proj = wx, py
            seg_actions = []
        else:
            seg_actions.append(action)

    result = [(start[0], start[1], "move")]
    for sx, sy, ex, ey, actions in segments:
        if (ex, ey) == (sx, sy):
            continue
        if "jump" in actions:
            action = "jump"
        elif "fall" in actions and abs(ex - sx) > 1:
            action = "bridge"
        elif ey < sy and (sy - ey) > 7:
            action = "pillar"
        elif ey < sy:
            action = "move"
        elif ey > sy:
            action = "fall"
        else:
            action = "move"
        result.append((ex, ey, action))

    if result[-1][:2] != goal:
        result.append((goal[0], goal[1], result[-1][2]))
    return result


def _dist_to_ground(tw, wx, wy, max_depth=20):
    for d in range(max_depth):
        if _solid(tw, wx, wy + d):
            return d
    return max_depth


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
            cost = _step_cost(dy)
            dtg = _dist_to_ground(tw, nx, ny) if dx != 0 else 0
            if dx != 0:
                cost += 2 + dtg
            ng = cur_g + cost
            npos = (nx, ny)
            if ng < g.get(npos, math.inf):
                g[npos] = ng
                if dy == 1:
                    action = "fall"
                elif dx != 0 and dtg > 0:
                    action = "bridge"
                    bridge_nodes.add(npos)
                else:
                    action = "move"
                prev[npos] = ((cx, cy), action)
                h = abs(goal_wx - nx) + abs(goal_wy - ny)
                heapq.heappush(heap, _Node(ng + h, nx, ny))

        if _standable(tw, cx, cy) or (cx, cy) in bridge_nodes:
            envelope = _jump_envelope(_GROUND_MOVEMENT, max_cols=_MAX_BRIDGE + 1)
            for js in (1, -1):
                for col in range(1, len(envelope)):
                    nx = cx + js * col
                    if nx < x_min or nx > x_max:
                        break
                    arc_dy = envelope[col]
                    blocked = False
                    for i in range(col):
                        arc_y = cy + envelope[i]
                        bx = cx + js * i
                        if _solid(tw, bx, arc_y) or _solid(tw, bx, arc_y - 1):
                            blocked = True
                            break
                    if blocked:
                        break
                    for ny in range(cy + arc_dy, min(cy + arc_dy + 4, y_max + 1)):
                        if _standable(tw, nx, ny):
                            cost = col * 0.5 + _step_cost(ny - cy)
                            ng = cur_g + cost
                            npos = (nx, ny)
                            if ng < g.get(npos, math.inf):
                                g[npos] = ng
                                action = "jump"
                                prev[npos] = ((cx, cy), action)
                                h = abs(goal_wx - nx) + abs(goal_wy - ny)
                                heapq.heappush(heap, _Node(ng + h, nx, ny))
                            break

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


    t0 = time.time()
    result = astar2(state, sign)
    dt = time.time() - t0
    print(f"[time] astar2 {dt*1000:.0f}ms")

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
        labels = [{"wx": path[-1][0], "wy": path[-1][1],
                   "text": f"goal len={len(path)} cost={total_cost:.1f}",
                   "r": 255, "g": 200, "b": 0}]
        prev_wx, prev_y = pcx, feet_y
        prev_action = None
        rise_run = 0
        rise_start_y = feet_y
        rise_x = pcx
        for wx, wy, action in path:
            if action == "bridge":
                adx = abs(wx - prev_wx)
                dy_per_step = (wy - prev_y) / max(adx, 1)
                for i, bx in enumerate(range(prev_wx + sign, wx, sign)):
                    by = int(prev_y + dy_per_step * (i + 1))
                    tiles.append({"wx": bx, "wy": by, "r": 180, "g": 0, "b": 255})
            elif action == "jump":
                adx = abs(wx - prev_wx)
                js = 1 if wx > prev_wx else -1
                envelope = _jump_envelope(_GROUND_MOVEMENT, max_cols=adx + 1)
                for i in range(adx + 1):
                    bx = prev_wx + js * i
                    by = prev_y + envelope[i]
                    tiles.append({"wx": bx, "wy": by, "r": 100, "g": 255, "b": 100})
                arc_end_y = prev_y + envelope[adx]
                for y in range(arc_end_y, wy):
                    tiles.append({"wx": wx, "wy": y, "r": 100, "g": 255, "b": 100})
            node_color = (255, 80, 80) if action == "pillar" else (255, 200, 0) if action == "jump" else (180, 0, 255) if action == "bridge" else (100, 220, 255)
            tiles.append({"wx": wx, "wy": wy, "r": node_color[0], "g": node_color[1], "b": node_color[2]})
            if wy > prev_y and action not in ("bridge", "jump"):
                for y in range(prev_y, wy):
                    tiles.append({"wx": wx, "wy": y, "r": 255, "g": 140, "b": 0})
                if rise_run > 0:
                    c = (255, 80, 80) if rise_run > 7 else (100, 255, 100)
                    labels.append({"wx": rise_x, "wy": rise_start_y - rise_run,
                                   "text": f"pillar {rise_run}" if rise_run > 7 else f"rise {rise_run}",
                                   "r": c[0], "g": c[1], "b": c[2]})
                    rise_run = 0
            elif wy < prev_y and action not in ("bridge", "jump"):
                if rise_run == 0:
                    rise_start_y = prev_y
                    rise_x = wx
                rise_run += 1
            else:
                if rise_run > 0:
                    c = (255, 80, 80) if rise_run > 7 else (100, 255, 100)
                    labels.append({"wx": rise_x, "wy": rise_start_y - rise_run,
                                   "text": f"pillar {rise_run}" if rise_run > 7 else f"rise {rise_run}",
                                   "r": c[0], "g": c[1], "b": c[2]})
                    rise_run = 0
            prev_wx, prev_y = wx, wy
            prev_action = action
        if rise_run > 0:
            c = (255, 80, 80) if rise_run > 7 else (100, 255, 100)
            labels.append({"wx": rise_x, "wy": rise_start_y - rise_run,
                           "text": f"pillar {rise_run}" if rise_run > 7 else f"rise {rise_run}",
                           "r": c[0], "g": c[1], "b": c[2]})
        _post("/path_vis_tiles", tiles)
        _post("/debug_labels", labels)

    time.sleep(2.0)
