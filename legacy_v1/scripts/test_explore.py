"""方向探索验证：往一个方向持续走，打印位置/biome，看连不连续、卡不卡。

这是第二类导航(没有具体坐标,只有方向+地形条件)的正解，对应 milestone1 找丛林。
用法: python scripts/test_explore.py left    (或 right)
      可选第二参 = 目标biome,到了自动停: python scripts/test_explore.py right jungle
Ctrl-C 停。
"""
import sys
import time
import json
import urllib.request

sys.path.insert(0, "src")
from terraria_agent.cerebellum.nav_client import NavClient  # noqa: E402


def state() -> dict:
    r = urllib.request.Request("http://127.0.0.1:17878/state", method="GET")
    with urllib.request.urlopen(r, timeout=2) as resp:
        return json.loads(resp.read().decode())


def tile(s: dict) -> tuple[int, int]:
    pp = s["player"]["pos"]
    return int((pp["x"] + s["player"]["width"] / 2) / 16), int((pp["y"] + s["player"]["height"]) / 16)


def main() -> None:
    direction = sys.argv[1] if len(sys.argv) > 1 else "right"
    target_biome = sys.argv[2] if len(sys.argv) > 2 else None
    sign = -1 if direction == "left" else 1

    nav = NavClient()
    nav.start_direction(sign)
    print(f"explore {direction} (sign={sign}), target_biome={target_biome}")

    last_tile = None
    stuck = 0
    try:
        while True:
            time.sleep(0.3)
            s = state()
            t = tile(s)
            biome = s.get("biome", "")
            res = nav.poll_direction()

            moved = last_tile is None or abs(t[0] - last_tile[0]) + abs(t[1] - last_tile[1]) >= 1
            stuck = 0 if moved else stuck + 1
            last_tile = t

            flag = "" if moved else f"  STUCK x{stuck}"
            print(f"  pos={t} biome={biome!r} nav={res.status}{flag}")

            if res.status == "failed":
                print(f"STOP: nav failed -> {res.human}")
                break
            if target_biome and biome == target_biome:
                print(f"REACHED biome={biome}")
                nav.stop_direction()
                break
            if stuck >= 20:
                print("STOP: stuck 6s, no progress")
                nav.stop_direction()
                break
    except KeyboardInterrupt:
        nav.stop_direction()
        print("cancelled")


if __name__ == "__main__":
    main()
