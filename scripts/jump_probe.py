import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv()

import urllib.request, json

BASE = "http://127.0.0.1:17878"

def post(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=2) as r:
        return json.loads(r.read())

def get_state():
    with urllib.request.urlopen(f"{BASE}/state", timeout=2) as r:
        return json.loads(r.read())

print("输入 frames direction（如 '6 right'），回车移动，ctrl+c 退出")

while True:
    try:
        line = input("> ").strip()
        if not line:
            continue
        parts = line.split()
        frames = int(parts[0])
        direction = parts[1] if len(parts) > 1 else "right"

        time.sleep(1.0)
        s0 = get_state()
        x0 = s0["player"]["pos"]["x"]

        post("/control", {direction: True})
        time.sleep(frames / 60.0)
        post("/control", {})

        time.sleep(0.5)
        s1 = get_state()
        x1 = s1["player"]["pos"]["x"]

        dx_tiles = abs(x1 - x0) / 16.0
        print(f"frames={frames} 位移={dx_tiles:.1f}格")

    except KeyboardInterrupt:
        break
    except Exception as e:
        print(f"错误: {e}")
