import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient, scan_standable, scan_skyline

perception = TerraBlindClient()

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

    print(f"\n[地图] pos=({pcx},{feet_y}) dir={p.direction}")
    print("       (@=玩家, ^=skyline, s=站立点, #=solid)")
    for row in rows:
        print(row)

    time.sleep(2.0)
