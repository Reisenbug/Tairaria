import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient, scan_standable, scan_skyline
from terraria_agent.terrain_astar import astar

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
                pillar_tiles.add((cur_x, cur_y + i))
        if edge.action in ("bridge", "pillar_bridge"):
            bridge_y = wy
            x0, x1 = (wx, cur_x) if wx > cur_x else (cur_x, wx)
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
    path_cols = {}
    if path:
        cur_x, cur_y = pcx, feet_y
        for wx, wy, edge in path:
            x0, x1 = (cur_x, wx) if wx > cur_x else (wx, cur_x)
            for col in range(x0, x1 + 1):
                t = col / max(abs(wx - cur_x), 1)
                interp_y = round(cur_y + (wy - cur_y) * t)
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
        goal_wx, goal_wy, _ = path[-1]
        print(f"\n[地图] pos=({pcx},{feet_y}) dir={direction} goal=({goal_wx},{goal_wy}) steps={len(path)}")
        for pwx, pwy, pedge in path:
            print(f"  ({pwx},{pwy}) {pedge.action} dx={pedge.dx} dy={pedge.dy} cost={pedge.cost:.1f}")
    else:
        print(f"\n[地图] pos=({pcx},{feet_y}) dir={direction} no path")
    print("       (@=玩家, *=waypoint, P=pillar, B=bridge, ^=skyline, s=站立点)")
    for row in rows:
        print(row)

    time.sleep(2.0)
