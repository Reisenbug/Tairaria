"""
Start/stop segmented nav.
Usage:
  python test_segnav.py rel <dx> <dy>
  python test_segnav.py abs <gx> <gy>
  python test_segnav.py stop
"""
import sys, json, urllib.request

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def post(p, d): return json.loads(opener.open(urllib.request.Request(f"http://127.0.0.1:17878{p}", data=json.dumps(d).encode(), method="POST"), timeout=5).read())
def state():
    r = urllib.request.Request("http://127.0.0.1:17878/state", method="GET")
    return json.loads(opener.open(r, timeout=3).read())

if len(sys.argv) < 2:
    print(__doc__); sys.exit(1)

if sys.argv[1] == "stop":
    print(post("/stop_seg_nav", {})); sys.exit(0)

if len(sys.argv) < 4:
    print(__doc__); sys.exit(1)

mode = sys.argv[1]
a, b = int(sys.argv[2]), int(sys.argv[3])
if mode == "rel":
    s = state(); pp = s["player"]["pos"]
    pcx = int((pp["x"] + s["player"]["width"] / 2) / 16)
    pcy = int((pp["y"] + s["player"]["height"]) / 16)
    gx, gy = pcx + a, pcy + b
else:
    gx, gy = a, b
print(f"goal=({gx},{gy})")
print(post("/start_seg_nav", {"gx": gx, "gy": gy}))
