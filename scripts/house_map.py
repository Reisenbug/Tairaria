#!/usr/bin/env python3
"""Scan the house and print it as an ASCII map in LOCAL coordinates, so you can point at
cells and say where the walls go.

Reference frame (same as foundation.py):
  local x : 1..21 across the foundation (x=1 leftmost, x=21 rightmost / the step-5 pillar)
  local y : 0 = the floor row the furniture sits on; NEGATIVE = up (toward the roof),
            POSITIVE = down (into the base). Printed with up at the top, like the screen.

You must give the anchor: the WORLD column of local x=21 (the rightmost pillar) and the
world row of the floor. If you don't know them, run foundation.py once — it prints end_x
and floor_row — or pass --probe to have this script find them from the player's position.
"""
import argparse, json, sys, urllib.request

MOD = "http://127.0.0.1:17878"
_op = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def post(path, payload=None):
    req = urllib.request.Request(
        f"{MOD}{path}", data=json.dumps(payload or {}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with _op.open(req, timeout=10) as r:
        return json.loads(r.read().decode())


def probe(x, y):
    return post("/probe_cell", {"x": x, "y": y})


# tile-type → single glyph for the map
def glyph(cell):
    if not cell.get("has_tile"):
        return "·" if cell.get("wall_type", cell.get("wall", 0)) else " "
    t = cell.get("tile_type", -1)
    return {
        19: "=",   # platform (foundation / roof / pillar)
        30: "#",   # wood block
        18: "T",   # workbench
        32: "田",  # table
        34: "h",   # chair
        93: "░",   # wood wall (as a tile? usually wall, but just in case)
    }.get(t, "?")


ap = argparse.ArgumentParser()
ap.add_argument("--end-x", type=int, help="world column of local x=21 (rightmost pillar)")
ap.add_argument("--floor", type=int, help="world row of the floor (local y=0)")
ap.add_argument("--up", type=int, default=12, help="rows to show above the floor")
ap.add_argument("--down", type=int, default=3, help="rows to show below the floor")
args = ap.parse_args()

if args.end_x is None or args.floor is None:
    # derive from the player: assume they're standing on the foundation near the right end.
    o = post("/origin")
    print(f"[hint] player origin = ({o['cx']},{o['cy']}). "
          f"Pass --end-x and --floor explicitly for an exact frame.", file=sys.stderr)
    if args.end_x is None:
        args.end_x = o["cx"]     # rough: assume player is at the right pillar
    if args.floor is None:
        args.floor = o["cy"]

base_x1 = args.end_x - 20        # local x=1
print(f"frame: local x=1 → world {base_x1}, x=21 → world {args.end_x}; floor row = {args.floor}")
print(f"       (· = back wall, space = empty, = platform, # block, T bench, 田 table, h chair)\n")

# header: local x numbers
xs = list(range(1, 22))
print("      " + "".join(str(x % 10) for x in xs))

for ly in range(-args.up, args.down + 1):
    wy = args.floor + ly
    row = []
    for lx in xs:
        wx = base_x1 + (lx - 1)
        row.append(glyph(probe(wx, wy)))
    tag = "floor" if ly == 0 else f"{ly:+d}"
    print(f"y={ly:>3} " + "".join(row) + f"  {tag}")
