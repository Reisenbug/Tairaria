"""
Visualize waypoint generation.
Usage:
  python test_waypoints.py <gx> <gy>            # absolute world tile
  python test_waypoints.py rel <dx> <dy>        # relative to player
"""
import sys, json, urllib.request

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def get_state():
    r = urllib.request.Request("http://127.0.0.1:17878/state", method="GET")
    return json.loads(opener.open(r, timeout=3).read())

if len(sys.argv) >= 4 and sys.argv[1] == "rel":
    dx, dy = int(sys.argv[2]), int(sys.argv[3])
    s = get_state()
    pp = s["player"]["pos"]
    pcx = int((pp["x"] + s["player"]["width"] / 2) / 16)
    pcy = int((pp["y"] + s["player"]["height"]) / 16)
    gx, gy = pcx + dx, pcy + dy
elif len(sys.argv) >= 3:
    gx, gy = int(sys.argv[1]), int(sys.argv[2])
else:
    print(__doc__); sys.exit(1)

data = json.dumps({"gx": gx, "gy": gy}).encode()
r = urllib.request.Request("http://127.0.0.1:17878/debug_waypoints", data=data, method="POST")
resp = json.loads(opener.open(r, timeout=3).read())
print(f"start: {resp['start']}")
print(f"goal:  ({gx}, {gy})")
print(f"waypoints ({len(resp['waypoints'])}): {resp['waypoints']}")
