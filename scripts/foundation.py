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
    with _op.open(req, timeout=10) as r:
        return json.loads(r.read().decode())


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
        time.sleep(0.3)
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

print("\n✓ foundation complete")
