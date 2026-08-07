#!/usr/bin/env python3
"""房址探针:跑一次 scan_house,在游戏里把结论画出来,同时在终端打 ASCII 图。

游戏里的颜色:绿=空(可用),红=被占。找到了就画选中的框;没找到就画出发点那个框,
一眼看出是被什么挡住的。

    python3 house_site.py                # 从玩家脚下找 21x10
    python3 house_site.py -w 21 -h 10 -r 200
    python3 house_site.py --at 4795 328  # 只看这个左下角行不行,不搜
"""
import argparse, json, urllib.request

MOD = "http://127.0.0.1:17878"
_op = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def post(path, payload=None):
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(MOD + path, data=data, method="POST")
    with _op.open(req, timeout=15) as r:
        return json.loads(r.read().decode() or "{}")


def terrain(cx, cy, w, h):
    return post("/terrain", {"cx": cx, "cy": cy, "w": w, "h": h})


def draw(bx, by, w, h):
    """把 (bx,by) 左下角的 w×h 框打成 ASCII。'.'=空,其它=占着。"""
    # /terrain 以 (cx,cy) 为中心,所以给它一个足够大的窗口再自己裁
    pad = 2
    cx, cy = bx + w // 2, by - h // 2
    tw, th = w + pad * 2, h + pad * 2
    t = terrain(cx, cy, tw, th)
    rows, x0, y0 = t.get("rows", []), t.get("x0"), t.get("y0")
    if not rows:
        print("  (读不到地形)")
        return None
    blocked = 0
    out = []
    for iy in range(h):
        wy = by - (h - 1 - iy)        # 从上往下打
        line = []
        for ix in range(w):
            wx = bx + ix
            ry, rx = wy - y0, wx - x0
            ch = rows[ry][rx] if 0 <= ry < len(rows) and 0 <= rx < len(rows[ry]) else "?"
            if ch != ".":
                blocked += 1
            line.append(ch)
        out.append(f"  {wy:>6} |{''.join(line)}|")
    print(f"  左下角 ({bx},{by})  右上角 ({bx + w - 1},{by - h + 1})")
    print("\n".join(out))
    print(f"         +{'-' * w}+   占着 {blocked}/{w * h} 格" + ("  ← 可用" if blocked == 0 else ""))
    return blocked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-w", type=int, default=21)
    ap.add_argument("-H", "--height", type=int, default=10)
    ap.add_argument("-r", "--range", type=int, default=200)
    ap.add_argument("--at", nargs=2, type=int, metavar=("X", "Y"),
                    help="只检查这个左下角,不搜")
    a = ap.parse_args()

    if a.at:
        # 只看这一个左下角。不走 scan_house —— 它 range=0 也还会在这一列上下试 60 行,
        # 画出来的会是它自己挑的那个框,不是你问的这个。
        bx, by = a.at
        print(f"检查 ({bx},{by}) 能不能放下 {a.w}x{a.height}:")
        draw(bx, by, a.w, a.height)
        return

    o = post("/origin", {})
    print(f"玩家在 ({o.get('cx')},{o.get('cy')}),找 {a.w}x{a.height} …")
    sf = post("/scan_house", {"w": a.w, "h": a.height, "range": a.range})
    print(json.dumps(sf, ensure_ascii=False))
    if not sf.get("found"):
        print(f"没找到(扫了 {sf.get('scanned')} 格)。画的是出发点那个框,红=挡路的:")
        draw(o.get("cx"), o.get("cy"), a.w, a.height)
        return
    bx, by = sf["at"]
    d = abs(bx - o.get("cx", 0)) + abs(by - o.get("cy", 0))
    print(f"找到:左下角 ({bx},{by}),离玩家 {d} 格。游戏里已用绿框标出。")
    draw(bx, by, a.w, a.height)


if __name__ == "__main__":
    main()
