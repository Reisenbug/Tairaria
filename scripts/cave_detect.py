import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv()

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient

_CLOUD_TYPES = {189, 196}
_THICK_THRESHOLD = 20


def has_overhead(tw, pcx, head_y):
    for dy in range(1, 16):
        t = tw.tile_at(pcx, head_y - dy)
        if t is None:
            continue
        if t.type in _CLOUD_TYPES:
            return False
        if t.solid:
            return True
    return False


def count_roof_thickness(tw, cx, head_y):
    first_solid_dy = None
    for dy in range(1, 30):
        t = tw.tile_at(cx, head_y - dy)
        if t is None:
            continue
        if t.type in _CLOUD_TYPES:
            return 0
        if t.solid:
            first_solid_dy = dy
            break
    if first_solid_dy is None:
        return 0
    count = 0
    for dy in range(first_solid_dy, first_solid_dy + 20):
        t = tw.tile_at(cx, head_y - dy)
        if t is not None and t.solid and t.type not in _CLOUD_TYPES:
            count += 1
        else:
            break
    return count


def find_overhead_edge(tw, pcx, head_y, cave_sign):
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


def detect_cave(tw, pcx, head_y, sign):
    thicknesses = []
    for i in range(1, 16):
        cx = pcx + sign * i
        thick = count_roof_thickness(tw, cx, head_y)
        thicknesses.append(thick)
    max_thick = max(thicknesses) if thicknesses else 0
    is_cave = max_thick >= _THICK_THRESHOLD
    return is_cave, thicknesses


perception = TerraBlindClient()

while True:
    state = perception.detect(frame=None)
    p = state.player
    tw = state.tile_window
    if tw is None or not tw.rows:
        print("no tile_window")
        time.sleep(0.5)
        continue

    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    head_y = int(p.pos[1] / 16.0)

    overhead = has_overhead(tw, pcx, head_y)
    print(f"overhead={overhead}")

    for direction, sign in [("right", 1), ("left", -1)]:
        if not overhead:
            print(f"{direction} [no overhead]")
            continue
        is_cave, thicknesses = detect_cave(tw, pcx, head_y, sign)
        thick_str = " ".join(str(t) for t in thicknesses)
        if is_cave:
            edge_i = find_overhead_edge(tw, pcx, head_y, sign)
            walk_back = max(1, edge_i + 2)
            print(f"{direction} [cave★ walk_back={walk_back} edge_i={edge_i}] | {thick_str}")
        else:
            print(f"{direction} [{'cave★' if is_cave else '-'}] | {thick_str}")
    print()
    time.sleep(0.5)
