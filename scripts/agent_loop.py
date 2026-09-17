"""激进版编排层:LLM 出计划,快判层做每一步的判断,代码只管调原语。

和 run_task 的区别:那边每走一步都要唤醒大模型(RPM=10,每轮硬等 6.5s),所以循环里
不敢有判断,只能写死。这里把循环里的判断全交给 fastjudge(260ms,不限流),
大模型只在【开局出计划】和【真的走不通】时才醒。

入口: /tb ai <目标>
"""
import json
import time

import fastjudge

MAX_STEPS = 40
MAX_REPLANS = 3


def _facts(sp, goal, plan, idx, last_result, results):
    """喂给快判层的现场。【只给判断要用的证据】,不给整份世界快照 --
    塞太多噪音会让三档之间分不出来,概率摊平成 confidence=0,门控就永远不触发。"""
    op = plan[idx] if idx < len(plan) else {}
    kind = op.get("op", "?")
    f = {"goal": goal, "step_kind": kind, "hp": None, "player_cell": None}

    try:
        st = sp.mod_get("/state")
        p = st.get("player", {})
        pos = p.get("pos", {})
        f["hp"] = p.get("hp")
        px, py = round(pos.get("x", 0) / 16), round(pos.get("y", 0) / 16)
        f["player_cell"] = [px, py]
        # 要用的东西在不在背包里,是 no_item 这一档唯一的依据
        inv = [it.get("name") for it in (st.get("equipment", {}).get("items", []) or [])]
        f["inventory"] = inv[:20]
    except Exception:
        px = py = None

    # 目标坐标解析得出来才谈得上远近。解析不出来本身就是证据
    target = op.get("at") or op.get("to")
    if target is not None:
        got = sp.resolve_arg(target, results)
        if got:
            tx, ty = (got["x"], got["y"]) if isinstance(got, dict) else (got[0], got[1])
            f["target_cell"] = [tx, ty]
            if px is not None:
                f["target_distance_cells"] = abs(tx - px) + abs(ty - py)
        else:
            f["target_unresolved"] = str(target)

    for k in ("name", "what", "tool", "slot"):
        if op.get(k) is not None:
            f[k] = op[k]
    if last_result:
        f["previous_step_result"] = last_result[:200]
    return f


def _run_plan(goal, sp, plan, results):
    """走完一份计划。返回 (走到第几步, 最后一个结果, 是不是中途卡死了)。
    这里【只管执行】,"目标到底达成没有"由调用方在计划跑完之后单独判。"""
    idx, last = 0, None
    while idx < len(plan) and idx < MAX_STEPS:
        op = plan[idx]
        facts = _facts(sp, goal, plan, idx, last, results)

        pre = fastjudge.ask("action_sanity", facts)
        print(f"[fastjudge] {idx} {op.get('op')} will_work={pre['will_work']} blocker={pre['blocker']}")
        # 【以 blocker 为准,不看 will_work】。will_work 是 Score,三档连续量中间档吸概率,
        # 实测 conf 只有 0.42~0.62;blocker 是互斥 Choice,同样现场能到 0.72~0.88
        blocker = pre["blocker"]
        if blocker.value not in (None, "none", "unknown") and blocker.sure():
            print(f"[agent] 第{idx}步预判失败 blocker={blocker.value}")
            last = json.dumps({"error": "precheck_failed", "blocker": blocker.value}, ensure_ascii=False)
        else:
            try:
                last = sp.exec_op(op, results)
            except Exception as e:
                last = json.dumps({"error": str(e)}, ensure_ascii=False)
            print(f"[agent] {idx}/{len(plan)} {op.get('op')} -> {last[:200]}")

        if not sp.op_failed(last):
            idx += 1
            continue

        # 失败了才分诊。retry_same 当场重来,不为它唤醒大模型
        kind = sp.failure_kind(op.get("op", "?"), last)
        if kind == "not_a_failure":
            idx += 1
            continue
        if kind == "retry_same":
            try:
                last = sp.exec_op(op, results)
            except Exception as e:
                last = json.dumps({"error": str(e)}, ensure_ascii=False)
            if not sp.op_failed(last):
                idx += 1
                continue
        return idx, last, True      # 这一步真的走不通,交给上层重规划

    return idx, last, False


_HOW_MANY = {"1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6_to_10": 6}


def wanted_rounds(goal):
    """目标要求做几轮。【读意图归快判,数次数归代码】-- 问"达成没有"是让它凭空推断世界状态,
    实测置信只有 0.13;问"目标说要几次"证据全在文本里,实测 0.84~0.99。
    返回 None = 没有明确次数,不做硬校验。"""
    r = fastjudge.ask("goal_quantity", {"goal": goal})
    counted, how = r["counted"], r["how_many"]
    print(f"[fastjudge] 数量 counted={counted.value} how_many={how.value}({how.confidence:.2f})")
    if counted.value is None or counted.value < fastjudge.NOUL_YES or not how.sure():
        return None
    return _HOW_MANY.get(how.value)


def _rounds_in(plan):
    """计划里排了几轮。一轮 = 一个真正作用于世界的动作(use/interact/craft/fight),
    find/nav 只是为它做准备"""
    return sum(1 for p in plan if p.get("op") in ("use", "interact", "craft", "fight", "loot"))


def run(goal, sp):
    """sp = second_player 模块。所有原语和 LLM 调用都借它的,这里不重复实现。"""
    sp.say(f"(激进模式)目标:{goal}", bot=True)
    said, plan = sp.plan_goal(goal)
    if not plan:
        sp.say("没规划出来,退回工具循环。", bot=True)
        return False
    if said:
        sp.say(said)

    results = {}
    t0 = time.monotonic()
    steps = 0
    want = wanted_rounds(goal)   # None = 目标没说次数,不做硬校验

    for attempt in range(MAX_REPLANS + 1):
        idx, last, stalled = _run_plan(goal, sp, plan, results)
        steps += idx

        # 【计划排得够不够,代码自己数】。同一句"砍两棵树"LLM 出过 6 步也出过 3 步,
        # 忠实跑完 3 步就宣布成功,等于把规划的漏洞当结果
        rounds = _rounds_in(plan[:idx])
        short = want is not None and rounds < want
        if short:
            print(f"[agent] 目标要{want}轮,计划只排了{rounds}轮")

        if not stalled and not short:
            dt = time.monotonic() - t0
            print(f"[agent] 完 {steps}步 {dt:.0f}s replans={attempt} "
                  f"{'快判在线' if fastjudge.ENABLED else '快判离线'}")
            sp.say("做完了。", bot=True)
            return True

        if attempt >= MAX_REPLANS:
            break

        # 【告诉它差几轮】。只说"没达成"的话它下一版计划照样可能只排一轮
        why = f"第{idx}步走不通" if stalled else f"目标要{want}轮,这份计划只排了{rounds}轮"
        sp.say(f"{why},重新想。", bot=True)
        said, plan = sp.plan_goal(goal, fail_ctx={
            "step": idx,
            "op": plan[idx].get("op") if stalled and idx < len(plan) else "(计划已跑完)",
            "result": (last or "")[:300],
            "done": [p.get("op") for p in plan[:idx]]})
        if not plan:
            break
        if said:
            sp.say(said)

    sp.say("试了几轮还是没成,我先停下。", bot=True)
    print(f"[agent] 停 {steps}步 {time.monotonic() - t0:.0f}s")
    return False
