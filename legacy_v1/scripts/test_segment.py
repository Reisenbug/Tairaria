"""
Test windowed segment A*.
Usage:
  python test_segment.py rel <dx> <dy> [radius]
  python test_segment.py abs <gx> <gy> [radius]
"""
import sys, json, urllib.request

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def post(path, data):
    r = urllib.request.Request(f"http://127.0.0.1:17878{path}", data=json.dumps(data).encode(), method="POST")
    return json.loads(opener.open(r, timeout=10).read())

def get_state():
    r = urllib.request.Request("http://127.0.0.1:17878/state", method="GET")
    return json.loads(opener.open(r, timeout=3).read())

if len(sys.argv) < 4:
    print(__doc__); sys.exit(1)

mode = sys.argv[1]
a, b = int(sys.argv[2]), int(sys.argv[3])
radius = int(sys.argv[4]) if len(sys.argv) > 4 else 25

if mode == "rel":
    s = get_state()
    pp = s["player"]["pos"]
    pcx = int((pp["x"] + s["player"]["width"] / 2) / 16)
    pcy = int((pp["y"] + s["player"]["height"]) / 16)
    gx, gy = pcx + a, pcy + b
else:
    gx, gy = a, b

print(f"goal=({gx},{gy}) radius={radius}")
resp = post("/debug_segment_plan", {"gx": gx, "gy": gy, "radius": radius})
if "path" in resp:
    p = resp["path"]
    print(f"path len={len(p)} cost={resp.get('cost')}")
    for n in p:
        print(f"  ({n['wx']},{n['wy']}) {n['action']}")
else:
    print(resp)
