import sys, os, time, json, urllib.request, heapq, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dataclasses import dataclass, field
from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient, scan_skyline

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
    y_min, y_max = oy, oy + tw.height - 1

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
                path.append(pos)
                pos = prev[pos]
            path.reverse()
            return path

        cur_g = g.get((cx, cy), math.inf)
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            nx, ny = cx + dx, cy + dy
            if nx < x_min or nx > x_max or ny < y_min or ny > y_max:
                continue
            if _solid(tw, nx, ny):
                continue
            ng = cur_g + 1
            npos = (nx, ny)
            if ng < g.get(npos, math.inf):
                g[npos] = ng
                prev[npos] = (cx, cy)
                h = abs(goal_wx - nx) + abs(goal_wy - ny)
                heapq.heappush(heap, _Node(ng + h, nx, ny))

    explored = set(g.keys())
    tiles = []
    for wx, wy in explored:
        tiles.append({"wx": wx, "wy": wy, "r": 180, "g": 60, "b": 60})
    tiles.append({"wx": goal_wx, "wy": goal_wy, "r": 255, "g": 200, "b": 0})
    _post("/path_vis_tiles", tiles)
    print(f"[astar2] no path {start}→{goal} explored={len(explored)}")
    return []


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

    path = astar2(state, sign)

    if not path:
        print(f"[vis] no path at ({pcx},{feet_y})")
    else:
        print(f"[path] ({pcx},{feet_y})→{path[-1]} len={len(path)}")
        tiles = [{"wx": pcx, "wy": feet_y, "r": 255, "g": 255, "b": 255}]
        for wx, wy in path:
            tiles.append({"wx": wx, "wy": wy, "r": 100, "g": 220, "b": 255})
        _post("/path_vis_tiles", tiles)
        _post("/debug_labels", [{"wx": path[-1][0], "wy": path[-1][1],
                                  "text": f"goal len={len(path)}",
                                  "r": 255, "g": 200, "b": 0}])

    time.sleep(2.0)
