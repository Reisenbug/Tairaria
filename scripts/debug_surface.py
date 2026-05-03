import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient, scan_surface

perception = TerraBlindClient()

_CONT_THRESHOLD = 6
_SCAN_COLS = 30


def segments(surface, tw):
    segs = []
    pit_edges = set()
    seg = []
    for rx in range(tw.width):
        wx = tw.origin[0] + rx
        sy = surface.get(wx)
        if not seg:
            if sy is not None:
                seg = [(wx, sy)]
        else:
            prev_sy = seg[-1][1]
            if sy is None or abs(sy - prev_sy) > _CONT_THRESHOLD:
                pit_edges.add(seg[-1][0])
                segs.append(seg)
                seg = []
                if sy is not None:
                    pit_edges.add(wx)
                    seg = [(wx, sy)]
            else:
                seg.append((wx, sy))
    if seg:
        segs.append(seg)
    return segs, pit_edges


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
    sign = 1 if p.direction == "right" else -1

    surface = scan_surface(tw)
    segs, pit_edges = segments(surface, tw)

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
                continue
            if surface.get(wx) == wy:
                if wx in pit_edges:
                    row += "E"
                else:
                    row += "^"
                continue
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

    player_seg_idx = next((i for i, seg in enumerate(segs) if any(wx == pcx for wx, _ in seg)), None)
    next_seg = segs[player_seg_idx + 1] if player_seg_idx is not None and player_seg_idx + 1 < len(segs) else None
    target = next_seg[0] if next_seg else None
    print(f"\n[地图] pos=({pcx},{feet_y}) dir={p.direction}  segments={len(segs)}  target={target}")
    print("       (@=玩家, ^=落脚点, E=段边缘, #=solid)")
    for row in rows:
        print(row)

    time.sleep(2.0)
