"""连续导航验证：给一串地表坐标，RouteRunner 依次走完，打印每段进度。

用法: python scripts/test_route.py 1100,520 1140,525 1180,520 ...
不带参数则用内置示例(需按你的地表改)。Ctrl-C 或走完自动停。
"""
import sys
import time
import urllib.request

sys.path.insert(0, "src")
from terraria_agent.cerebellum.route_runner import RouteRunner  # noqa: E402


def player_tile() -> tuple[int, int]:
    r = urllib.request.Request("http://127.0.0.1:17878/state", method="GET")
    import json
    with urllib.request.urlopen(r, timeout=2) as resp:
        s = json.loads(resp.read().decode())
    pp = s["player"]["pos"]
    pcx = int((pp["x"] + s["player"]["width"] / 2) / 16)
    pcy = int((pp["y"] + s["player"]["height"]) / 16)
    return pcx, pcy


def parse(args: list[str]) -> list[tuple[int, int]]:
    route = []
    for a in args:
        x, y = a.split(",")
        route.append((int(x), int(y)))
    return route


def main() -> None:
    route = parse(sys.argv[1:]) if len(sys.argv) > 1 else []
    if not route:
        print("给坐标: python scripts/test_route.py x1,y1 x2,y2 ...")
        return

    runner = RouteRunner()
    pt = player_tile()
    print(f"start from {pt}, route={route}")
    res = runner.start(route, player_tile=pt)
    print(f"  {res.human}")

    last_idx = res.index
    try:
        while runner.active:
            time.sleep(0.1)
            res = runner.tick()
            if res.index != last_idx:
                print(f"  -> {res.human}")
                last_idx = res.index
        print(f"DONE: status={res.status} {res.human}")
    except KeyboardInterrupt:
        runner.cancel()
        print("cancelled")


if __name__ == "__main__":
    main()
