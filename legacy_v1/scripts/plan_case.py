"""
一次性打印当前位置的 /plan_path 结果，附带分析。
用法: python scripts/plan_case.py [sign=1]
sign=1 向右，sign=-1 向左
"""
import sys, os, json, urllib.request

sign = int(sys.argv[1]) if len(sys.argv) > 1 else 1
_BASE = "http://127.0.0.1:17878"


def _get(path):
    resp = urllib.request.urlopen(_BASE + path, timeout=3)
    return json.loads(resp.read())


def _post(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(_BASE + path, data=body, method="POST")
    resp = urllib.request.urlopen(req, timeout=5)
    return json.loads(resp.read())


state = _get("/state")
p = state["player"]
pcx = int((p["pos"]["x"] + p["width"] / 2.0) / 16.0)
feet_y = int((p["pos"]["y"] + p["height"]) / 16.0)
print(f"[player] ({pcx},{feet_y}) sign={sign}")

result = _post("/plan_path", {"sign": sign})
path = result.get("path", [])
cost = result.get("cost", 0)

if not path:
    print("[result] NO PATH")
    sys.exit(0)

goal = path[-1]
print(f"[result] goal=({goal['wx']},{goal['wy']}) len={len(path)} cost={cost:.1f}")
print()

# Action sequence summary
action_counts = {}
segments = []
cur_action = None
seg_start = 0
for i, n in enumerate(path):
    a = n["action"]
    action_counts[a] = action_counts.get(a, 0) + 1
    if a != cur_action:
        if cur_action is not None:
            segments.append((cur_action, seg_start, i - 1, path[seg_start], path[i-1]))
        cur_action = a
        seg_start = i
segments.append((cur_action, seg_start, len(path)-1, path[seg_start], path[-1]))

print("[actions] " + " | ".join(f"{a}×{c}" for a, c in action_counts.items()))
print()
print("[segments]")
for action, s, e, first, last in segments:
    dx = last["wx"] - first["wx"]
    dy = last["wy"] - first["wy"]
    count = e - s + 1
    print(f"  {action:8s} ({first['wx']},{first['wy']})→({last['wx']},{last['wy']})  dx={dx:+d} dy={dy:+d}  n={count}")

print()
print("[nodes]")
for n in path:
    print(f"  {n['action']:8s} ({n['wx']:4d},{n['wy']:4d})")
