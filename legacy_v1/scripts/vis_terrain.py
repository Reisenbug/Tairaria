"""
Usage:
  python scripts/vis_terrain.py              # centered on player
  python scripts/vis_terrain.py 2449 318     # centered on given tile
  python scripts/vis_terrain.py 2449 318 60 30  # w=60 h=30

Legend: # solid  - platform  + other  . air  @ player
"""
import http.client, json, sys

PORT = 17878

def get_state():
    c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=2)
    c.request('GET', '/state')
    return json.loads(c.getresponse().read())

def get_terrain(cx, cy, w, h):
    data = json.dumps({'cx': cx, 'cy': cy, 'w': w, 'h': h}).encode()
    c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=2)
    c.request('POST', '/terrain', data, {'Content-Type': 'application/json'})
    return json.loads(c.getresponse().read())

args = sys.argv[1:]
cx = cy = 0
w, h = 60, 25

if len(args) >= 2:
    cx, cy = int(args[0]), int(args[1])
if len(args) >= 4:
    w, h = int(args[2]), int(args[3])

state = get_state()
p = state['player']
pcx = int((p['pos']['x'] + p['width'] / 2) / 16)
feetY = int((p['pos']['y'] + p['height']) / 16)

if cx == 0 and cy == 0:
    cx, cy = pcx, feetY

terrain = get_terrain(cx, cy, w, h)
rows = terrain['rows']
x0, y0 = terrain['x0'], terrain['y0']

print(f"center=({cx},{cy}) player=({pcx},{feetY}) x0={x0} y0={y0}")
print(f"{'':4s}" + "".join(str((x0+i)%100).rjust(1) for i in range(0, w, 10)).ljust(w))

for row_idx, row in enumerate(rows):
    wy = y0 + row_idx
    line = list(row)
    # mark player position
    for dx in range(2):
        px = pcx + dx - 1
        if x0 <= px < x0 + w:
            if feetY - 3 <= wy <= feetY:
                line[px - x0] = '@'
    print(f"{wy:4d}|{''.join(line)}|")
