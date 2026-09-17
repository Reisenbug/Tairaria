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
CANDIDATES = 8      # find 至少拿这么多候选,够不着就换下一个


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


# 【查询类不做预检】。它们不碰世界、不吃物品、失败也无害,而"背包里有没有料"这种判据
# 对它们根本不适用 -- recipe 查铅头盔配方被判 no_item 拦了四次,整局耗死在第0步
_READ_ONLY = {"recipe", "recipe_tree", "find", "find_biome", "probe", "measure", "say", "ask"}


_BLOCKERS = {
    "none": "没问题,能做",
    "no_item": "背包里没有这一步要用的东西",
    "no_tool": "缺合适的工具(镐/斧)",
    "too_far": "目标太远,够不着",
    "bad_spot": "那个位置放不下/站不住/挥不到",
    "unknown": "说不清",
}


def _precheck_all(sp, goal, plan, results):
    """【一次问完整份计划的预检】。一步一问是 6x260ms 串行等待,而官方说独立问题
    并行求值不加延迟 -- 打包成一个请求还是 260ms。

    返回 {步号: blocker字符串}。只读步不问,拿不到答案的步不拦(留空)。"""
    todo = [i for i, op in enumerate(plan)
            if op.get("op") not in _READ_ONLY and i < MAX_STEPS]
    if not todo:
        return {}

    state = {"goal": goal, "steps": {}}
    try:
        st = sp.mod_get("/state")
        p = st.get("player", {})
        pos = p.get("pos", {})
        state["hp"] = p.get("hp")
        state["player_cell"] = [round(pos.get("x", 0) / 16), round(pos.get("y", 0) / 16)]
        state["inventory"] = [it.get("name") for it in
                              (st.get("equipment", {}).get("items", []) or [])][:20]
    except Exception:
        pass

    for i in todo:
        op = plan[i]
        d = {"op": op.get("op")}
        for k in ("name", "what", "tool", "slot", "at", "to"):
            if op.get(k) is not None:
                d[k] = op[k]
        state["steps"][f"step_{i}"] = d

    # 【坐标此刻多半还没解析】。计划里是 $t.pos 这种占位符,find 执行到才有值 --
    # 所以这一趟只拦"缺物品/缺工具"这类和位置无关的,位置问题留给执行时那次现场预检
    qs = {f"step_{i}": fastjudge.Choice(
        instructions=f"这份计划的 step_{i} 现在做得成吗?做不成的话最主要的障碍是什么?"
                     f"坐标写成 $xx.pos 的说明执行到那步才知道,别因为这个判 too_far。",
        criteria=_BLOCKERS) for i in todo}

    ans = fastjudge.ask_many(state, qs, tag="precheck_batch")
    # 【放行的也记下来】。只记拦下的话,放行的步查不到就又现场问一次,白花 260ms
    out = {}
    for i in todo:
        a = ans.get(f"step_{i}")
        if a and a.value not in (None, "none", "unknown") and a.sure():
            out[i] = a.value
        elif a and a.value == "none" and a.sure():
            out[i] = "none"
    stop = {i: v for i, v in out.items() if v != "none"}
    print(f"[fastjudge] 批量预检 {len(todo)}步一次问完"
          + (f",拦下 {stop}" if stop else ",都能做"))
    return out


def _run_plan(goal, sp, plan, results):
    """走完一份计划。返回 (走到第几步, 最后一个结果, 是不是中途卡死了)。
    这里【只管执行】,"目标到底达成没有"由调用方在计划跑完之后单独判。"""
    idx, last = 0, None
    skip = set()        # 够不着的目标坐标。find 重跑时要绕开它们,否则原地打转
    # 开局一次问完整份计划。批量拦得住"缺物品/缺工具"这类和位置无关的
    batch = _precheck_all(sp, goal, plan, results)
    while idx < len(plan) and idx < MAX_STEPS:
        op = plan[idx]

        blocked = None
        if op.get("op") not in _READ_ONLY:
            # 批量问过的不用再问一次。"none" = 批量放行,不是拦截理由
            blocked = batch.pop(idx, None)
            if blocked == "none":
                blocked = None
            elif blocked is None:
                # 【位置类只能现场判】。批量那趟坐标还是 $t.pos 占位符,
                # 要等 find 执行完才有真值,所以 bad_spot/too_far 留到这儿
                facts = _facts(sp, goal, plan, idx, last, results)
                pre = fastjudge.ask("action_sanity", facts)
                print(f"[fastjudge] {idx} {op.get('op')} will_work={pre['will_work']} blocker={pre['blocker']}")
                # 【以 blocker 为准,不看 will_work】。will_work 是 Score,三档连续量中间档吸概率,
                # 实测 conf 只有 0.42~0.62;blocker 是互斥 Choice,同样现场能到 0.72~0.88
                b = pre["blocker"]
                if b.value not in (None, "none", "unknown") and b.sure():
                    blocked = b.value

        if blocked:
            print(f"[agent] 第{idx}步预判失败 blocker={blocked}")
            last = json.dumps({"error": "precheck_failed", "blocker": blocked}, ensure_ascii=False)
        else:
            # 【find 要多拿几个候选】。计划里默认 n=1,只拿一个的话第一个够不着就没得换了,
            # 而 find_tiles 端点不支持排除,换目标只能靠客户端在候选里滤
            if op.get("op") == "find" and op.get("n", 1) < CANDIDATES:
                op = {**op, "n": CANDIDATES}
                plan[idx] = op
            try:
                last = sp.exec_op(op, results)
            except Exception as e:
                last = json.dumps({"error": str(e)}, ensure_ascii=False)
            print(f"[agent] {idx}/{len(plan)} {op.get('op')} -> {last[:200]}")
            # 【find 的结果要过一遍黑名单】。exec_op 总把第一个写进 results,
            # 不滤的话重跑 find 只会挑回刚拉黑的那一个,来回打转
            if skip and op.get("op") == "find" and op.get("id"):
                alt = _pick_unskipped(last, skip)
                if alt:
                    results[op["id"]] = {"pos": {"x": alt["x"], "y": alt["y"]}, "tiles": [alt]}
                    print(f"[agent] 换目标 -> ({alt['x']},{alt['y']})")
                else:
                    last = json.dumps({"error": "no_reachable_target",
                                       "tried": len(skip)}, ensure_ascii=False)
            # 【没走到就是没走到】。nav 停在十几格外时 done=false,但 op_failed 不认 stopped_short,
            # 于是下一步照挥,必然够不着 -- 之后被当成"这个目标不行"拉黑,八个候选轮一遍全废
            if op.get("op") == "nav":
                last = _nav_shortfall(last) or last

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

        # 【这个目标不行就换一个,别惊动大模型】。砍树那局:树梢坐标够不着,四次重规划出四份
        # 一样的计划。模板早就是这么做的(skip 掉够不着的,locate 下一个)
        back = _retarget(sp, plan, idx, results, skip, blocked)
        if back is not None:
            idx = back
            continue
        return idx, last, True      # 换不动了,交给上层重规划

    return idx, last, False


# 这几类说明"这个目标不行",不是"做法不行"。换个目标就完事,重规划是浪费
_RETARGETABLE = {"bad_spot", "too_far"}


def _retarget(sp, plan, idx, results, skip, blocked):
    """把当前目标拉黑,回退到产生它的那个 find 步重跑。返回要跳回的步号,换不动就 None。"""
    if blocked not in _RETARGETABLE:
        return None
    ref = plan[idx].get("at") or plan[idx].get("to")
    if not ref:
        return None
    got = sp.resolve_arg(ref, results)
    if not got:
        return None
    xy = (got["x"], got["y"]) if isinstance(got, dict) else (got[0], got[1])
    skip.add(xy)

    # 往前找最近的 find:它产生的 id 正是这一步引用的那个
    want_id = str(ref).lstrip("$").split(".")[0]
    for j in range(idx - 1, -1, -1):
        if plan[j].get("op") in ("find", "find_biome") and plan[j].get("id") == want_id:
            print(f"[agent] {xy} 够不着({blocked}),拉黑重找 -> 回到第{j}步")
            return j
    return None


def _nav_shortfall(out):
    """nav 说自己没走到就交一份失败现场。不叫 bad_spot -- 那是"这个目标不行",
    会把矿脉拉黑;这里目标没毛病,是人没到位,换几个候选还是同样够不着。"""
    try:
        d = json.loads(out)
    except Exception:
        return None
    if d.get("status") != "stopped_short":
        return None
    return json.dumps({"error": "not_arrived", "dist": d.get("dist"),
                       "note": d.get("note"), "state": d.get("state")},
                      ensure_ascii=False)


def _pick_unskipped(out, skip):
    """find 的结果里挑第一个没被拉黑的。find_tiles 端点不支持排除,只能拿回来自己滤"""
    try:
        d = json.loads(out)
    except Exception:
        return None
    tiles = [t for t in (d.get("tiles") or []) if (t["x"], t["y"]) not in skip]
    return tiles[0] if tiles else None


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
        # 【一件改变世界的事都没做 = 没做完】。这条比数量校验更根本:目标没说数量时
        # want 是 None,数量校验整个跳过,于是"只查了个配方"也算完成(现场:铅头盔那局)
        short = rounds == 0 or (want is not None and rounds < want)
        if short:
            print(f"[agent] 目标要{want or '至少1'}轮,计划只排了{rounds}轮")

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
        # 【把失败原因原样带上】。不带的话 LLM 每轮拿到一样的输入,出一样的计划,
        # 四次重规划四份相同的 plan(现场:铅头盔那局)
        said, plan = sp.plan_goal(goal, fail_ctx={
            "step": idx,
            "op": plan[idx].get("op") if stalled and idx < len(plan) else "(计划已跑完)",
            "result": (last or "")[:300],
            "why": why,
            "done": [p.get("op") for p in plan[:idx]]})
        if not plan:
            break
        if said:
            sp.say(said)

    sp.say("试了几轮还是没成,我先停下。", bot=True)
    print(f"[agent] 停 {steps}步 {time.monotonic() - t0:.0f}s")
    return False
