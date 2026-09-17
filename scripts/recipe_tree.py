"""把一个目标物品展开成配方树,算出总共要去世界上弄到哪些东西。

纯代码,不叫 LLM 也不叫 Jev:配方是游戏里的确定数据,问模型只会更慢更错。
模型的活从叶子开始 -- 树说"要 40 个秘银矿",怎么弄到手才是模型的事。
"""
import json
import math

MAX_DEPTH = 12


def _recipe(sp, name):
    try:
        r = sp.mod_post("/recipe", {"name": name})
    except Exception:
        return None
    if not isinstance(r, dict):
        return None
    rs = r.get("recipes") or []
    return rs[0] if rs else None


def expand(sp, name, qty=1):
    """展开 name x qty。返回 (叶子总表, 步骤清单, 台子清单)。

    叶子 = 配方表里做不出来的东西:矿石/木头/怪物掉落/箱子开出来的。
    台子 = 要站在旁边才能合成的,自己也可能要先造出来(工作台->熔炉->铁砧)。
    """
    leaves, steps, stations = {}, [], {}
    memo = {}

    def go(item, need, depth, path):
        # 同一个物品在树里会出现几十次(每个铁砧都要一遍工作台)。展开一次,之后只累加数量
        if depth > MAX_DEPTH or item in path:
            leaves[item] = leaves.get(item, 0) + need
            return
        r = memo.get(item)
        if r is None:
            r = _recipe(sp, item)
            memo[item] = r if r is not None else False
        if r is False or r is None:
            leaves[item] = leaves.get(item, 0) + need
            return

        have = 0
        for ing in r.get("ingredients") or []:
            if (ing.get("name") or ing.get("internal")) == item:
                have = ing.get("have") or 0
        short = need - have
        if short <= 0:
            return

        per = max(1, int(r.get("amount") or 1))
        rounds = math.ceil(short / per)

        for st in r.get("stations") or []:
            tile = st.get("tile") or ""
            if tile in stations:
                continue
            items = st.get("items") or []
            if not items:
                # 恶魔祭坛这类世界里天生的,做不出来,得去找。和矿石一样是叶子,只是获取方式不同
                stations[tile] = {"tile": tile, "make": None, "found_in_world": True}
                continue
            pick = next((i for i in items if (i.get("have") or 0) > 0), items[0])
            pname = pick.get("name") or pick.get("internal")
            stations[tile] = {"tile": tile, "make": pname,
                              "have": pick.get("have") or 0, "found_in_world": False}
            if (pick.get("have") or 0) <= 0:
                go(pname, 1, depth + 1, path | {item})

        for ing in r.get("ingredients") or []:
            iname = ing.get("name") or ing.get("internal")
            if not iname or iname == item:
                continue
            want = (ing.get("need") or 0) * rounds - (ing.get("have") or 0)
            if want > 0:
                go(iname, want, depth + 1, path | {item})

        steps.append({"craft": item, "rounds": rounds, "amount": per,
                      "stations": [s.get("tile") for s in (r.get("stations") or [])]})

    go(name, qty, 0, frozenset())
    return leaves, steps, stations


def summary(sp, name, qty=1):
    leaves, steps, stations = expand(sp, name, qty)
    need_world = [s for s in stations.values() if s["found_in_world"]]
    return json.dumps({
        "goal": f"{name} x{qty}",
        "gather": [{"name": k, "count": v} for k, v in
                   sorted(leaves.items(), key=lambda kv: -kv[1])],
        "craft_order": [s["craft"] for s in steps],
        "stations": [s["tile"] for s in stations.values()],
        "stations_to_find": [s["tile"] for s in need_world],
        "note": "gather 是要去世界上弄到手的(挖/砍/打怪/开箱);craft_order 是从底往上的合成顺序",
    }, ensure_ascii=False)
