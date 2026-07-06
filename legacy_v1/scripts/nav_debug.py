"""
Debug nav: compose action sequences relative to current player position.

Usage:
    python scripts/nav_debug.py
Edit the run_actions() call at the bottom to specify the sequence.

Actions:
    ("move", n)      - move n tiles forward (sign direction)
    ("pillar", n)    - pillar up n tiles
    ("jump",)        - single jump forward (uses A* frames if available)
    ("fall", n)      - fall n tiles down
"""
import json, urllib.request, sys, time

BASE = "http://127.0.0.1:17878"
SIGN = 1  # 1=right, -1=left

def req(path, body=None, method=None):
    if body is None:
        body = b"{}"
    if isinstance(body, dict):
        body = json.dumps(body).encode()
    m = method or ("POST" if body else "GET")
    r = urllib.request.Request(f"{BASE}{path}", data=body, method=m)
    with urllib.request.urlopen(r, timeout=5) as resp:
        return json.loads(resp.read())

def get_player():
    s = req("/state", method="GET")
    p = s["player"]
    px = float(p["pos"]["x"]); py = float(p["pos"]["y"])
    w = float(p["width"]); h = float(p["height"])
    cx = int((px + w/2) / 16)
    fy = int((py + h) / 16)
    return cx, fy

def build_path(cx, fy, actions):
    """Build absolute nav path from relative actions."""
    nodes = []
    x, y = cx, fy

    for action in actions:
        kind = action[0]

        if kind == "move":
            n = action[1]
            for _ in range(n):
                x += SIGN
                nodes.append({"wx": x, "wy": y, "action": "move"})

        elif kind == "fall":
            n = action[1]
            for _ in range(n):
                y += 1
                nodes.append({"wx": x, "wy": y, "action": "fall"})

        elif kind == "pillar":
            n = action[1]
            y -= n
            nodes.append({"wx": x, "wy": y, "action": "pillar"})

        elif kind == "jump":
            # minimal jump node: no frames, NavCoordinator falls back to JumpCoordinator
            dx = action[1] if len(action) > 1 else 5
            x += SIGN * dx
            nodes.append({"wx": x, "wy": y, "action": "jump"})

        else:
            print(f"[warn] unknown action {kind}")

    return nodes

def send_path(nodes):
    path_json = json.dumps({"sign": SIGN, "path": nodes}, separators=(',', ':'))
    result = req("/nav_set_path", body=path_json.encode())
    print(f"set_path: {result}")

def wait_done(timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = req("/nav_done", method="GET")
            if s.get("done"):
                print("nav done")
                return True
        except Exception:
            pass
        time.sleep(0.5)
    print("timeout")
    return False

if __name__ == "__main__":
    cx, fy = get_player()
    print(f"player at cx={cx} feetY={fy}")

    # ---- Edit this sequence ----
    actions = [
        ("move", 5),
        ("jump", 6),
        ("pillar", 5),
        ("jump", 6),
    ]
    # ----------------------------

    nodes = build_path(cx, fy, actions)
    print(f"path ({len(nodes)} nodes):")
    for n in nodes:
        print(f"  ({n['wx']},{n['wy']}) {n['action']}")

    send_path(nodes)
    wait_done(timeout=60)
