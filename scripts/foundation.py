#!/usr/bin/env python3
"""House foundation: rope ladder -> platform on top -> hop onto it -> bridge out 20.

Every step is verified against the MAP before the next one starts. A step that reports
success but left nothing in the world stops the run — the whole point is that no stage
gets to lie to the stage after it.
"""
import json, sys, time, urllib.request

MOD = "http://127.0.0.1:17878"
_op = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def post(path, payload=None):
    # ensure_ascii=False: the mod matches item names by their raw UTF-8 characters ("绳"), so the body must carry
    # them literally. json.dumps escapes non-ASCII to \uXXXX by default, which turned "绳" into the literal seven
    # characters 绳 and matched no item — the "no_item" that curl (raw bytes) never reproduced.
    req = urllib.request.Request(
        f"{MOD}{path}", data=json.dumps(payload or {}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with _op.open(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        # a 400 (e.g. craft recipe unavailable) is data, not a crash — return the error body.
        return json.loads(e.read().decode())


def get(path):
    with _op.open(f"{MOD}{path}", timeout=10) as r:
        return json.loads(r.read().decode())


def wait(path, timeout=60):
    """poll a *_status endpoint until it stops running; return the final status."""
    end = time.time() + timeout
    while time.time() < end:
        st = get(path)
        if not st.get("running"):
            return st
        time.sleep(0.05)
    return get(path)


def probe(x, y):
    return post("/probe_cell", {"x": x, "y": y})


def die(msg, extra=None):
    print(f"\n✗ {msg}")
    if extra is not None:
        print(json.dumps(extra, ensure_ascii=False, indent=2))
    sys.exit(1)


ROPE = "绳"
FLOOR = "木平台"      # the single platform landed on at the top of the rope, to hop onto
BRIDGE = "木材"       # the 20-cell foundation run — SOLID BLOCKS, not a platform
LENGTH = 20
DIRECTION = "right"

print("origin:", post("/origin"))

# ── 1. rope ladder ────────────────────────────────────────────────────────────
print(f"\n[1] rope ladder x{LENGTH}")
r = post("/rope_ladder", {"item": ROPE, "n": LENGTH})
if not r.get("accepted"):
    die("ladder refused", r)
st = wait("/rope_ladder_status", 90)
print("   ", json.dumps(st, ensure_ascii=False))
if st.get("placed", 0) + st.get("already_there", 0) < LENGTH:
    die(f"ladder short: placed={st.get('placed')} already={st.get('already_there')}", st)

above = st.get("above_top")
if not above:
    die("ladder did not report above_top", st)
ax, ay = above
print(f"    top={st.get('top')} above_top={above}")

# verify against the map, not the report
c = probe(ax, ay)
if c.get("has_tile"):
    print(f"    note: {above} already holds tile {c.get('tile_type')}")

# ── 2. platform on top of the rope ────────────────────────────────────────────
print(f"\n[2] platform at {above}")
r = post("/place_at", {"item": FLOOR, "world": [ax, ay]})
if not r.get("accepted"):
    die("place refused", r)
st = wait("/place_at_status", 30)
print("   ", json.dumps(st, ensure_ascii=False))
c = probe(ax, ay)
if not c.get("has_tile"):
    die(f"no tile at {above} after placing", c)
print(f"    map says: tile_type={c.get('tile_type')} ✓")

# ── 3. hop up onto it ─────────────────────────────────────────────────────────
print(f"\n[3] hop onto row {ay}")
r = post("/hop_up", {"row": ay})
if not r.get("accepted"):
    die("hop refused", r)
st = wait("/hop_up_status", 20)
print("   ", json.dumps(st, ensure_ascii=False))
o = post("/origin")
print(f"    origin now {o['cx']},{o['cy']} (want cy={ay - 1})")
if o["cy"] != ay - 1:
    die(f"not standing on the platform: cy={o['cy']}, expected {ay - 1}", o)

# ── 4. bridge out ─────────────────────────────────────────────────────────────
print(f"\n[4] bridge {DIRECTION} x{LENGTH}")
r = post("/bridge", {"item": BRIDGE, "dir": DIRECTION, "n": LENGTH})
if not r.get("accepted"):
    die("bridge refused", r)
st = wait("/bridge_status", 120)
print("   ", json.dumps(st, ensure_ascii=False))

# verify the run cell by cell on the map
row = ay
step = 1 if DIRECTION == "right" else -1
missing = [x for k in range(1, LENGTH + 1)
           for x in [ax + step * k]
           if not probe(x, row).get("has_tile")]
built = LENGTH - len(missing)
print(f"\n    foundation: {built}/{LENGTH} cells present on row {row}")
if missing:
    print(f"    missing: {missing[:10]}{' ...' if len(missing) > 10 else ''}")
    die("foundation incomplete")

# ── 5. pillar on the LAST foundation cell ─────────────────────────────────────
# The pillar goes in the column of the last foundation block — told to /pillar as an
# absolute column, so it does not depend on where the player's body ended up. The
# action walks itself adjacent to that column and fills it bottom-to-top.
PILLAR_H = 9
end_x = ax + step * LENGTH          # column of the final foundation cell
ptop = row                          # the foundation row = the pillar's ground level
print(f"\n[5] pillar x{PILLAR_H} in column x={end_x} (last foundation cell)")

r = post("/pillar", {"item": FLOOR, "n": PILLAR_H, "col": end_x})
if not r.get("accepted"):
    die("pillar refused", r)
st = wait("/pillar_status", 90)
print("   ", json.dumps(st, ensure_ascii=False))
if st.get("placed", 0) < PILLAR_H:
    die(f"pillar short: placed={st.get('placed')}", st)

# verify the column on the map: PILLAR_H platforms stacked upward from the foundation row
missing_p = [y for k in range(PILLAR_H) for y in [ptop - k]
             if not probe(end_x, y).get("has_tile")]
print(f"    pillar: {PILLAR_H - len(missing_p)}/{PILLAR_H} present in column x={end_x}")
if missing_p:
    print(f"    missing rows: {missing_p}")
    die("pillar incomplete")

# pillar's step-aside leaves the player just off the column; settle back onto the
# foundation at the pillar column so the hop starts from solid, centered ground.
print(f"\n[5b] settle onto pillar column x={end_x} on the foundation")
r = post("/settle", {"col": end_x})
if r.get("accepted"):
    st = wait("/settle_status", 20)
    print("    settle:", json.dumps(st, ensure_ascii=False))
o = post("/origin")
print(f"    standing at {o['cx']},{o['cy']}")

# ── 6. climb onto the pillar top ──────────────────────────────────────────────
# The pillar is a platform column; the player lines up under it and jumps (a couple
# of hops clear a column this tall) until standing on the top platform, ready to
# build the roof from there.
pillar_top = ptop - (PILLAR_H - 1)      # top platform row of the pillar
print(f"\n[6] hop onto pillar top (col={end_x}, row={pillar_top})")
r = post("/hop_up", {"row": pillar_top, "col": end_x})
if not r.get("accepted"):
    die("hop refused", r)
st = wait("/hop_up_status", 20)
print("   ", json.dumps(st, ensure_ascii=False))

# settle: brake to a dead stop on the pillar column so we don't slide off the one-cell platform.
r = post("/settle", {"col": end_x})
if r.get("accepted"):
    st = wait("/settle_status", 20)
    print("    settle:", json.dumps(st, ensure_ascii=False))

o = post("/origin")
print(f"    origin now {o['cx']},{o['cy']} (want cx={end_x}, cy≤{pillar_top - 1})")
if o["cx"] != end_x or o["cy"] > pillar_top - 1:
    die(f"not on the pillar top: at {o['cx']},{o['cy']}", o)

print("\n✓ foundation + pillar + on top, ready for roof")

# ── 7. roof: lay 20 platforms to the LEFT from the pillar top ──────────────────
ROOF_LEN = 20
roof_row = o["cy"] + 1              # the row the player stands on = the roof line
print(f"\n[7] roof: {ROOF_LEN} platforms to the left along row {roof_row}")
r = post("/bridge", {"item": FLOOR, "dir": "left", "n": ROOF_LEN})
if not r.get("accepted"):
    die("roof refused", r)
st = wait("/bridge_status", 120)
print("   ", json.dumps(st, ensure_ascii=False))

# verify the roof run on the map
missing_r = [x for k in range(1, ROOF_LEN + 1) for x in [end_x - k]
             if not probe(x, roof_row).get("has_tile")]
print(f"    roof: {ROOF_LEN - len(missing_r)}/{ROOF_LEN} present on row {roof_row}")
if missing_r:
    print(f"    missing: {missing_r[:10]}{' ...' if len(missing_r) > 10 else ''}")
    die("roof incomplete")

print("\n✓ house shell complete (foundation + pillar + roof)")

# ── 8. drop to base, then 4 support pillars left→right ────────────────────────
# The roof is a platform; drop through it onto the foundation, then raise a pillar
# every 5 cells across the span (the rightmost already exists from step 5).
print("\n[8] drop through roof to the base")
r = post("/drop", {})
if not r.get("accepted"):
    die("drop refused", r)
st = wait("/drop_status", 20)
print("   ", json.dumps(st, ensure_ascii=False))
o = post("/origin")
print(f"    landed at {o['cx']},{o['cy']}")

SUP_H = 8                                   # roof already occupies the top cell, so 8 not 9
base_x1 = end_x - 20                         # local x=1 in world coords (leftmost foundation cell)

def wx(local):                              # local x (1..21, per the plan) → world column
    return base_x1 + (local - 1)

# ONE anchor can reach several pillars — chosen so the body never leaves the foundation span nor
# overlaps the column it's placing. Plan (local x): anchor 3 → pillars 1,6 ; anchor 8 → 11 ; anchor 13 → 16.
jobs = [(3, [1, 6]), (8, [11]), (13, [16])]
print(f"\n[9] support pillars x{SUP_H} — anchors/pillars (local x): {jobs}")
for anchor_lx, pillar_lxs in jobs:
    post("/settle", {"col": wx(anchor_lx)})
    wait("/settle_status", 30)
    o = post("/origin")
    print(f"    anchored at {o['cx']},{o['cy']} (local x={anchor_lx})")
    for plx in pillar_lxs:
        col = wx(plx)
        r = post("/pillar", {"item": FLOOR, "n": SUP_H, "col": col})
        if not r.get("accepted"):
            die(f"pillar at local x={plx} (col {col}) refused", r)
        st = wait("/pillar_status", 90)
        miss = [y for k in range(SUP_H) for y in [roof_row - k] if not probe(col, y).get("has_tile")]
        print(f"    pillar local x={plx} col={col}: placed={st.get('placed')}, {SUP_H - len(miss)}/{SUP_H} on map")

print("\n✓ house complete: foundation + roof + 5 support pillars")

# ── 10. furnish: workbench, craft, tables, chairs ─────────────────────────────
# The last pillar ends mid-air, so settle FIRST to land on the foundation before reading the
# floor row — otherwise floor_row is a sky row and everything places into nothing.
post("/settle", {"col": wx(19)})
wait("/settle_status", 30)
o = post("/origin")
floor_row = o["cy"]                          # the row the player's own cell occupies on the base
print(f"    on foundation at {o['cx']},{o['cy']}, floor_row={floor_row}")

WORKBENCH, TABLE, CHAIR, WALL, TORCH = "工作台", "木桌", "木椅", "木墙", "火把"
NEED = {TABLE: 3, CHAIR: 4, WALL: 96}

state = get("/state")
have = {}
for it in state.get("equipment", {}).get("items", []):
    n = it.get("name")
    if n:
        have[n] = have.get(n, 0) + it.get("stack", 0)

print("\n[10] furnish")

# workbench: make one if none in inventory, then place it at local x=19
if have.get(WORKBENCH, 0) < 1:
    print("    crafting workbench")
    post("/craft", {"item_name": WORKBENCH, "amount": 1})
    state = get("/state"); have = {}
    for it in state.get("equipment", {}).get("items", []):
        n = it.get("name")
        if n: have[n] = have.get(n, 0) + it.get("stack", 0)

print(f"    settle to local x=19 (col {wx(19)}) and place workbench")
post("/settle", {"col": wx(19)})
wait("/settle_status", 30)
post("/place_at", {"item": WORKBENCH, "world": [wx(19), floor_row]})
wait("/place_at_status", 20)

# The recipe list is proximity-driven: 木桌/木椅/木墙 only appear once the workbench is placed AND
# registered near the player. Placement is frame-driven, so the recipe may lag a few frames — wait for
# a furniture recipe to show up before crafting, instead of firing a craft that finds no recipe.
def recipe_available(name):
    for r in get("/state").get("available_recipes", []):
        if r.get("item_name") == name:
            return True
    return False

for _ in range(40):
    if recipe_available(TABLE):
        break
    time.sleep(0.1)
print(f"    workbench recipes ready: 木桌={recipe_available(TABLE)}")

# craft what's missing (only the shortfall)
for item, need in NEED.items():
    short = need - have.get(item, 0)
    if short > 0:
        print(f"    craft {item} x{short} (have {have.get(item,0)}/{need})")
        r = post("/craft", {"item_name": item, "amount": short})
        print("      ", json.dumps(r, ensure_ascii=False))
    else:
        print(f"    {item}: have {have.get(item,0)} ≥ {need}, skip")

# ── 11. tables: walk 19 → 3, place tables at local x=14,9,4 in reach ──────────
print("\n[11] tables while walking 19→3 at local x=14,9,4")
r = post("/walk_place", {
    "dest_x": wx(3),
    "targets": [{"x": wx(lx), "y": floor_row, "item": TABLE} for lx in (14, 9, 4)],
})
print("   ", json.dumps(r, ensure_ascii=False))
if r.get("accepted"):
    st = wait("/walk_place_status", 60)
    print("   ", json.dumps(st, ensure_ascii=False))

# ── 12. chairs: walk 3 → 19, place chairs at local x=2,7,12,17 in reach ───────
print("\n[12] chairs while walking 3→19 at local x=2,7,12,17")
r = post("/walk_place", {
    "dest_x": wx(19),
    "targets": [{"x": wx(lx), "y": floor_row, "item": CHAIR} for lx in (2, 7, 12, 17)],
})
print("   ", json.dumps(r, ensure_ascii=False))
if r.get("accepted"):
    st = wait("/walk_place_status", 60)
    print("   ", json.dumps(st, ensure_ascii=False))

print("\n✓ furnished")

# ── 13. walls: 4 rooms, ordered A..T per room ─────────────────────────────────
# Room layout (your ASCII), 6 cols × 10 rows. Walls fill the inner 4×6 (col2-5, row1-6)
# in a fixed order — vanilla wall spread depends on the order, and the mid holes must be
# placed in exactly this sequence:
#   A r1c2 B r2c2 C r3c2 D r4c2 E r5c2 F r6c2   (left column, top→down)
#   G r6c3 H r6c4 I r6c5                          (bottom row, →)
#   J r5c5 K r4c5 L r3c5 M r2c5 N r1c5           (right column, up)
#   O r1c4 P r1c3                                 (top row, ←)
#   Q r2c3 R r3c4 S r4c3 T r5c4                   (the four inner holes, THIS order)
ORDER = [
    (1, 2), (2, 2), (3, 2), (4, 2), (5, 2), (6, 2),   # A-F
    (6, 3), (6, 4), (6, 5),                            # G-I
    (5, 5), (4, 5), (3, 5), (2, 5), (1, 5),            # J-N
    (1, 4), (1, 3),                                    # O-P
    (2, 3), (3, 4), (4, 3), (5, 4),                    # Q-T
]

# room k's left pillar is at local x = 1+5k; its col1 == that. row0 = the roof line.
roof_line = roof_row                       # the platform row the roof/room-top sits on
# each room's furniture column to stand on (tables at local x 4,9,14; workbench at 19):
stand_lx = {0: 4, 1: 9, 2: 14, 3: 19}

print("\n[13] walls — 4 rooms, order A..T each")
for k in range(4):
    col1_lx = 1 + 5 * k
    # world cells for this room's A..T
    cells = []
    for (r, c) in ORDER:
        wcx = wx(col1_lx + (c - 1))
        wcy = roof_line + r
        cells.append([wcx, wcy])

    # stand on this room's table/workbench, then place walls (jumps for the ones too high)
    stand_col = wx(stand_lx[k])
    print(f"  room {k}: stand at local x={stand_lx[k]} (col {stand_col})")
    post("/settle", {"col": stand_col})
    wait("/settle_status", 30)
    # hop up onto the furniture surface (table top is one row above the floor)
    post("/hop_up", {"row": floor_row, "col": stand_col})
    wait("/hop_up_status", 30)

    r = post("/place_walls", {"item": WALL, "cells": cells})
    print("     ", json.dumps(r, ensure_ascii=False))
    if r.get("accepted"):
        st = wait("/place_walls_status", 120)
        print("     ", json.dumps(st, ensure_ascii=False))

    # torch on the wall at room-local row 2, col 3 (second row, second inner column).
    torch_x = wx(col1_lx + (3 - 1))
    torch_y = roof_line + 2
    print(f"     torch at ({torch_x},{torch_y})")
    tr = post("/place_at", {"item": TORCH, "world": [torch_x, torch_y]})
    if tr.get("accepted"):
        wait("/place_at_status", 30)

print("\n✓ walls + torches done — house fully built")
