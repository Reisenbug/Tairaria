"""单点导航验证：Python 发 /nav，现在走新 StateSpacePlanner(物理保真)。
确认 running/done/failed 状态机经 HTTP 通。
用法: python scripts/test_nav_single.py GX GY
"""
import sys
import time
import json
import urllib.request

sys.path.insert(0, "src")
from terraria_agent.cerebellum.nav_client import NavClient  # noqa: E402


def player_tile():
    r = urllib.request.Request("http://127.0.0.1:17878/state", method="GET")
    with urllib.request.urlopen(r, timeout=2) as resp:
        s = json.loads(resp.read().decode())
    pp = s["player"]["pos"]
    return int((pp["x"] + s["player"]["width"] / 2) / 16), int((pp["y"] + s["player"]["height"]) / 16)


def main():
    n = NavClient()
    pt = player_tile()
    if len(sys.argv) >= 3:
        gx, gy = int(sys.argv[1]), int(sys.argv[2])
    else:
        # 无参: 默认从当前位置往右 10 格、同高度。带一个参 = 相对偏移(负=左)。
        dx = int(sys.argv[1]) if len(sys.argv) == 2 else 10
        gx, gy = pt[0] + dx, pt[1]
        print(f"(相对目标 dx={dx})")
    print(f"from {pt} -> ({gx},{gy})")
    r = n.start(gx, gy, player_tile=pt)
    print(f"  start: status={r.status} reason={r.reason} {r.human}")
    if r.status == "failed":
        return
    for _ in range(200):
        time.sleep(0.2)
        r = n.poll()
        if r.status != "running":
            print(f"  END: status={r.status} reason={r.reason} {r.human}")
            return
    print("  TIMEOUT (still running after 40s)")
    n.stop()


if __name__ == "__main__":
    main()
