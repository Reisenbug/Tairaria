"""扔掉寻路,让 Jev 逐步开车。

看一张以人为中心的 ASCII 地形图,选一个按键,按几帧,再看一眼。没有势能场、没有 A*、
没有跳跃重放、没有任何容差表 -- 这些全是会漏的判据,换个游戏一行都留不下。
换个 2D 游戏要改的只有画图那一段。
"""
import json
import time

import fastjudge
from fastjudge import Choice

VIEW_W, VIEW_H = 31, 21        # 给 Jev 看多大一片。太大它抓不住重点,太小看不见坑
STEP_FRAMES = 12               # 一个动作按多久。60fps 下 0.2 秒,约走两三格
MAX_TURNS = 120
ARRIVE = 2                     # 离目标这么近就算到了

# 脚下那一格是 (0,0),dy>0 向下。每个动作 = 按哪些键 + 光标放哪
MOVES = {
    "left":       {"keys": ["left"]},
    "right":      {"keys": ["right"]},
    "jump_left":  {"keys": ["left", "jump"]},
    "jump_right": {"keys": ["right", "jump"]},
    "jump":       {"keys": ["jump"]},
    "dig_left":   {"keys": [], "dig": (-1, 0)},
    "dig_right":  {"keys": [], "dig": (1, 0)},
    "dig_down":   {"keys": [], "dig": (0, 1)},
    "dig_up":     {"keys": [], "dig": (0, -1)},
    "wait":       {"keys": []},
}

DRIVE_Q = {
    "move": Choice(
        instructions=(
            "这是 Terraria 里以你为中心的一张地形图,你是图正中的 @。"
            "# 是实心方块(挡路,可以挖),= 是平台(能站,能从下面跳上来),"
            "空格是空气,~ 是水,! 是岩浆(碰到会死),T 是你要去的目标方向。"
            "图的每一行是一排格子,越往下越深。你想靠近 T,下一步该怎么动?"
        ),
        criteria={
            "right": "往右走。右边是通的",
            "left": "往左走。左边是通的",
            "jump_right": "往右跳。右边有一格高的坎,或者要跳上右边的平台",
            "jump_left": "往左跳。左边有一格高的坎,或者要跳上左边的平台",
            "jump": "原地往上跳。头顶有平台要上去",
            "dig_right": "挖掉右边那格。右边被实心方块堵死了",
            "dig_left": "挖掉左边那格。左边被实心方块堵死了",
            "dig_down": "挖掉脚下那格,往下走。目标在下面",
            "dig_up": "挖掉头顶那格,往上开。目标在上面且跳不上去",
            "wait": "先别动。正在下落,或者旁边就是岩浆,动一下会死",
        },
    ),
}


def _expand(tiles):
    """把游程编码的 rows 摊成 [行][列] = (Type, SFlags)。"""
    grid = []
    for row in tiles["rows"]:
        cells = []
        for t, flags, n in row:
            cells.extend([(t, flags)] * n)
        grid.append(cells)
    return grid


def _char(cell):
    t, f = cell
    if f & 0b1000:  return "!"      # 岩浆。碰到就死,必须让它看见
    if f & 0b100:   return "~"
    if f & 0b1000000: return "="    # 平台:能站,也能从下面钻上去
    if f & 0b10:    return "#"
    if f & 0b1:     return "."      # 有东西但不挡路(草、火把)
    return " "


def _view(state, goal_cx, goal_cy):
    """画一张以人为中心的图,顺带把目标方向标在边上。"""
    tiles = state["tiles"]
    grid = _expand(tiles)
    ox, oy = tiles["origin"]["x"], tiles["origin"]["y"]
    px = round(state["player"]["pos"]["x"] / 16)
    py = round(state["player"]["pos"]["y"] / 16)
    cx, cy = px - ox, py - oy

    half_w, half_h = VIEW_W // 2, VIEW_H // 2
    lines = []
    for dy in range(-half_h, half_h + 1):
        line = []
        for dx in range(-half_w, half_w + 1):
            gx, gy = cx + dx, cy + dy
            if dx == 0 and dy == 0:
                line.append("@")
            elif 0 <= gy < len(grid) and 0 <= gx < len(grid[gy]):
                line.append(_char(grid[gy][gx]))
            else:
                line.append("?")
            # 目标在视野内就标出来,在视野外标到边上,方向不能丢
            if goal_cx - px == dx and goal_cy - py == dy and not (dx == 0 and dy == 0):
                line[-1] = "T"
        lines.append("".join(line))

    # 【视野外的目标要投到对的那条边】。只往左右两侧贴的话,正下方的目标会显示在左下角,
    # Jev 照着图往左走,而它其实该往下挖
    dx, dy = goal_cx - px, goal_cy - py
    if abs(dx) > half_w or abs(dy) > half_h:
        sx = dx / half_w if half_w else 0
        sy = dy / half_h if half_h else 0
        if abs(sx) >= abs(sy):
            ex = VIEW_W - 1 if dx > 0 else 0
            ey = half_h + int(round(dy / abs(sx))) if sx else half_h
        else:
            ey = VIEW_H - 1 if dy > 0 else 0
            ex = half_w + int(round(dx / abs(sy))) if sy else half_w
        ex = max(0, min(VIEW_W - 1, ex))
        ey = max(0, min(VIEW_H - 1, ey))
        row = list(lines[ey])
        row[ex] = "T"
        lines[ey] = "".join(row)
    return "\n".join(lines), px, py


def _do(sp, move, pick_slot):
    spec = MOVES[move]
    step = {"keys": list(spec["keys"]), "until": {"frames": STEP_FRAMES}}
    if "dig" in spec:
        dx, dy = spec["dig"]
        step["rel"] = [dx, dy]
        step["use"] = True
        step["keys"] = ["use_tile"]
        if pick_slot is not None:
            step["slot"] = pick_slot
    return sp.run_tool("act", {"steps": [step], "timeout_frames": STEP_FRAMES * 4})


def drive(sp, goal_cx, goal_cy, say=None):
    """一步一步走到 (goal_cx, goal_cy)。返回 (到了没有, 走了几步, 为什么停)。"""
    pick = sp._best_tool_slot("pick")
    stuck_at, stuck_n = None, 0

    for turn in range(MAX_TURNS):
        st = sp.mod_get("/state")
        view, px, py = _view(st, goal_cx, goal_cy)
        dist = abs(goal_cx - px) + abs(goal_cy - py)
        if dist <= ARRIVE:
            return True, turn, "arrived"

        # 原地不动就是卡住了。不靠 trigger 猜,靠位置说话
        if (px, py) == stuck_at:
            stuck_n += 1
            if stuck_n >= 8:
                return False, turn, "stuck"
        else:
            stuck_at, stuck_n = (px, py), 0

        hp = st.get("player", {}).get("hp")
        ans = fastjudge.ask_many(
            {"地形图": view,
             "目标在": f"{'右' if goal_cx > px else '左'}边 {abs(goal_cx - px)} 格,"
                       f"{'下' if goal_cy > py else '上'}方 {abs(goal_cy - py)} 格",
             "血量": hp,
             "站在地上": st.get("player", {}).get("on_ground"),
             "刚才做了": getattr(drive, "_last", "(开局)")},
            DRIVE_Q, tag="drive")
        mv = ans["move"]
        move = mv.value if mv.value in MOVES else "wait"
        drive._last = move
        print(f"[drive] {turn:3d} ({px},{py}) 离目标{dist:3d}  {move:11s} conf={mv.confidence:.2f}")
        _do(sp, move, pick)

    return False, MAX_TURNS, "out_of_turns"
