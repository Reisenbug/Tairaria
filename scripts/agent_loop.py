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


def run(goal, sp):
    """sp = second_player 模块。所有原语和 LLM 调用都借它的,这里不重复实现。"""
    sp.say(f"(激进模式)目标:{goal}", bot=True)
    said, plan = sp.plan_goal(goal)
    if not plan:
        sp.say("没规划出来,退回工具循环。", bot=True)
        return False
    if said:
        sp.say(said)

    results, idx, replans, last = {}, 0, 0, None
    t0 = time.monotonic()

    while idx < len(plan) and idx < MAX_STEPS:
        op = plan[idx]
        facts = _facts(sp, goal, plan, idx, last)

        # 做之前先判:这步现在做得成吗。拦一次省一趟 mod 往返 + 一轮重试。
        # 【Score 给的是 0..N-1 的位置】不是 criteria 文本,三档里 <0.5 才算落在"肯定失败"那档
        pre = fastjudge.ask("action_sanity", facts)
        # 【过了也要打】。只在失败时出声的话,全通过就一行日志都没有,看着像没接上
        print(f"[fastjudge] {idx} {op.get('op')} will_work={pre['will_work']} blocker={pre['blocker'].value}")
        if pre["will_work"].value is not None and pre["will_work"].value < 0.5 and pre["will_work"].sure():
            blocker = pre["blocker"].value
            print(f"[agent] 第{idx}步预判失败 blocker={blocker}")
            last = json.dumps({"error": "precheck_failed", "blocker": blocker}, ensure_ascii=False)
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

        replans += 1
        if replans > MAX_REPLANS:
            sp.say(f"第{idx}步反复失败,我停下了。", bot=True)
            return False
        sp.say(f"第{idx}步走不通,重新想。", bot=True)
        said, plan = sp.plan_goal(goal, fail_ctx={
            "step": idx, "op": op.get("op"), "result": last[:300],
            "done": [p.get("op") for p in plan[:idx]]})
        if not plan:
            return False
        if said:
            sp.say(said)
        idx = 0

    dt = time.monotonic() - t0
    print(f"[agent] 完 {idx}步 {dt:.0f}s replans={replans} {fastjudge.ENABLED and '快判在线' or '快判离线'}")
    sp.say("做完了。", bot=True)
    return True
