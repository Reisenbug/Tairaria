import json, urllib.request

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open("http://127.0.0.1:17878/state", timeout=1.0) as resp:
    d = json.loads(resp.read())

p = d["player"]
eq = d.get("equipment", {})
print(f"pos=({p['pos']['x']}, {p['pos']['y']})")
print(f"vel=({p['vel']['x']}, {p['vel']['y']})")
print(f"on_ground={p['on_ground']}")
print(f"in_liquid={p['in_liquid']}")
print(f"direction={p['direction']}")
print(f"biome={p['biome']}")
print(f"smart_cursor={eq.get('smart_cursor')}")
print(f"selected_slot={eq.get('selected_slot')}")

buffs = d.get("buffs", [])
if buffs:
    print(f"buffs={[b['name'] for b in buffs]}")

tiles = d.get("tiles", {})
if tiles:
    ox, oy = tiles["origin_x"], tiles["origin_y"]
    pcx = int((p['pos']['x'] + p.get('width', 20) / 2) / 16)
    pcy = int((p['pos']['y'] + p.get('height', 42)) / 16)
    print(f"player_tile=({pcx}, {pcy})")
    ry = pcy - oy
    rx = pcx - ox
    if 0 <= ry < len(tiles["rows"]):
        row = tiles["rows"][ry]
        col = 0
        for run in row:
            end = col + run["count"]
            if col <= rx < end:
                print(f"tile_at_feet: type={run['type']} sflags={run['sflags']}")
                break
            col = end
    if 0 <= ry - 3 < len(tiles["rows"]):
        row = tiles["rows"][ry - 3]
        col = 0
        for run in row:
            end = col + run["count"]
            if col <= rx < end:
                print(f"tile_above_head: type={run['type']} sflags={run['sflags']}")
                break
            col = end
