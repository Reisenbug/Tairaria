import sys, os, time, json, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient, scan_standable, scan_skyline
from terraria_agent.terrain_astar import astar

_BASE = "http://127.0.0.1:17878"

def _post(path, data):
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(_BASE + path, data=body, method="POST")
        urllib.request.urlopen(req, timeout=1)
    except Exception:
        pass

perception = TerraBlindClient()
direction = "left"
sign = 1 if direction == "right" else -1


def _planned_blocks(path, pcx, feet_y):
    pillar_tiles = set()
    bridge_tiles = set()
    cur_x, cur_y = pcx, feet_y
    for wx, wy, edge in path:
        if edge.action in ("pillar", "pillar_bridge"):
            rise = cur_y - wy
            for i in range(rise):
                pillar_tiles.add((cur_x, cur_y - 1 - i))
        if edge.action in ("bridge", "pillar_bridge"):
            bridge_y = wy - 1
            x0, x1 = (min(cur_x, wx), max(cur_x, wx))
            for bx in range(x0, x1 + 1):
                bridge_tiles.add((bx, bridge_y))
        cur_x, cur_y = wx, wy
    return pillar_tiles, bridge_tiles


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

    standable = scan_standable(tw)
    skyline = scan_skyline(tw)

    path = astar(state, sign)
    if path is None:
        print(f"[vis] living tree at ({pcx},{feet_y})")
    elif not path:
        goal_wx = pcx + sign * 40
        print(f"[vis] no path at ({pcx},{feet_y}) in_skyline={pcx in skyline} skyline_y={skyline.get(pcx)} goal_wx={goal_wx} goal_in_skyline={goal_wx in skyline}")
    path_cols = {}
    if path:
        cur_x, cur_y = pcx, feet_y
        for wx, wy, edge in path:
            adx = max(abs(wx - cur_x), 1)
            sx = 1 if wx > cur_x else -1
            for i in range(adx + 1):
                col = cur_x + sx * i
                interp_y = round(cur_y + (wy - cur_y) * i / adx)
                path_cols[col] = interp_y
            cur_x, cur_y = wx, wy
    path_nodes = {(wx, wy) for wx, wy, _ in path} if path else set()
    pillar_tiles, bridge_tiles = _planned_blocks(path, pcx, feet_y) if path else (set(), set())

    ox, oy = tw.origin
    rows = []
    for ry in range(tw.height):
        wy = oy + ry
        row = ""
        for rx in range(tw.width):
            wx = ox + rx
            dx = wx - pcx
            dy = wy - feet_y
            if dx in (0, 1) and dy >= -2 and dy <= 0:
                row += "@"
            elif (wx, wy) in pillar_tiles:
                row += "P"
            elif (wx, wy) in bridge_tiles:
                row += "B"
            elif (wx, wy) in path_nodes or path_cols.get(wx) == wy:
                row += "*"
            elif skyline.get(wx) == wy:
                row += "^"
            elif (wx, wy) in standable:
                row += "s"
            else:
                t = tw.tile_at(wx, wy)
                if t is None:
                    row += "?"
                elif t.solid:
                    row += "#"
                elif t.lava:
                    row += "!"
                elif t.water:
                    row += "~"
                else:
                    row += "."
        rows.append(f"{wy:4d} {row}")

    if path:
        _ACTION_COLOR = {
            "walk":         (100, 220, 255),
            "jump":         (100, 255, 100),
            "bridge":       (255, 180,   0),
            "pillar":       (255,  80,  80),
            "pillar_bridge":(255,  80, 255),
        }
        tiles = [{"wx": pcx, "wy": feet_y, "r": 255, "g": 255, "b": 255}]
        labels = []
        cx0, cy0 = pcx, feet_y
        for wx, wy, edge in path:
            r, g, b = _ACTION_COLOR.get(edge.action, (255, 255, 255))
            steps = abs(wx - cx0)
            for i in range(steps + 1):
                t = i / max(steps, 1)
                ix = int(cx0 + (wx - cx0) * t)
                iy = int(cy0 + (wy - cy0) * t)
                tiles.append({"wx": ix, "wy": iy, "r": r, "g": g, "b": b})
            reason_str = f" {edge.reason}" if edge.reason else ""
            labels.append({"wx": wx, "wy": wy,
                           "text": f"{edge.action} c={edge.cost:.0f} dx={edge.dx} dy={edge.dy}{reason_str}",
                           "r": r, "g": g, "b": b})
            cx0, cy0 = wx, wy
        _post("/path_vis_tiles", tiles)
        _post("/debug_labels", labels)

    time.sleep(2.0)
