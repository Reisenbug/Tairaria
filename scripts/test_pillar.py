"""
Test pillar: 3 cases — pillar 4, 6, 8 tiles from current position.
Each run: pillar up N tiles, wait for done, then report feetY delta.
"""
import json, urllib.request, time

BASE = "http://127.0.0.1:17878"

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

def send_pillar(cx, fy, rise, sign=1):
    target_wy = fy - rise
    nodes = [{"wx": cx, "wy": target_wy, "action": "pillar"}]
    body = json.dumps({"sign": sign, "path": nodes}, separators=(',', ':')).encode()
    return req("/nav_set_path", body=body)

def wait_done(timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = req("/nav_done", method="GET")
            if s.get("done"):
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False

def nav_stop():
    try:
        req("/nav_stop", body=b"{}")
    except Exception:
        pass

if __name__ == "__main__":
    for rise in [4, 6, 8]:
        cx, fy = get_player()
        print(f"\n--- pillar {rise} tiles: start cx={cx} feetY={fy} target_wy={fy - rise} ---")
        result = send_pillar(cx, fy, rise)
        print(f"set_path: {result}")
        done = wait_done(timeout=90)
        time.sleep(1.0)
        cx2, fy2 = get_player()
        delta = fy - fy2
        print(f"done={done} end feetY={fy2} rose={delta} (expected {rise})")
        if not done:
            nav_stop()
        time.sleep(2)
