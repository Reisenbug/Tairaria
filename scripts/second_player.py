"""TerraBlind second-player agent.

An LLM agent that plays Terraria alongside the human. The player types /tb <text> in game chat;
the agent runs a tool-calling loop driving the mod's HTTP primitives (state/find/nav/mine/...),
talks back through in-game chat, and — crucially — can ask the player a question mid-task and
BLOCK on their reply (the next /tb), then continue the SAME task. Not one-shot per /tb.

Run:    python scripts/second_player.py      (game running with the TerraBlind mod loaded)
Config: SECOND_PLAYER_API_URL / SECOND_PLAYER_MODEL / SECOND_PLAYER_API_KEY in .env,
        falling back to COMMANDER_* (same convention as llm_client.py).
"""

import html
import json
import os
import queue
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from dotenv import load_dotenv
from openai import OpenAI
from websockets.sync.client import connect as ws_connect

load_dotenv()

MOD = "http://127.0.0.1:17878"
POLL_S = 1.0
NAV_TIMEOUT_S = 240
NAV_REPORT_S = 12       # progress-note cadence while walking
MAX_TURNS = 60          # tool-loop turns per task (runaway guard)
HISTORY_MAX_MSGS = 80   # rolling conversation memory across tasks

# RATE LIMIT. The endpoint allows RPM requests per minute (default 10). Bursting past it makes the server silently
# QUEUE the extra call for ~60s — indistinguishable from a hung model unless we say so. So we self-throttle to one
# request per MIN_CALL_GAP_S, and whenever we do have to wait, print it loudly so the user knows it's the quota, not
# the model. Override RPM via env when the endpoint changes.
RPM = int(os.environ.get("SECOND_PLAYER_RPM") or os.environ.get("COMMANDER_RPM", "10"))
MIN_CALL_GAP_S = 60.0 / RPM + 0.5   # a little headroom over the exact window
_last_llm_call = 0.0

API_URL = os.environ.get("SECOND_PLAYER_API_URL") or os.environ.get("COMMANDER_API_URL", "https://api.openai.com/v1")
API_KEY = os.environ.get("SECOND_PLAYER_API_KEY") or os.environ.get("COMMANDER_API_KEY", "")
MODEL = os.environ.get("SECOND_PLAYER_MODEL") or os.environ.get("COMMANDER_MODEL", "")

client = OpenAI(base_url=API_URL, api_key=API_KEY, timeout=120, max_retries=1)


def throttle_llm():
    """Enforce the endpoint's RPM so we never burst into the server's silent ~60s queue. When we must wait, SAY SO —
    a visible '限流等待' line so the user never mistakes a quota wait for a hung model."""
    global _last_llm_call
    wait = MIN_CALL_GAP_S - (time.monotonic() - _last_llm_call)
    if wait > 0:
        print(f"⏳ 限流等待 {wait:.1f}s（RPM={RPM}，非模型卡顿）")
        say(f"（配额限流，等 {wait:.0f} 秒再动，别急）") if wait >= 5 else None
        time.sleep(wait)
    _last_llm_call = time.monotonic()

# bypass any http_proxy/https_proxy env vars — the mod is on localhost
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def mod_get(path):
    with _opener.open(f"{MOD}{path}", timeout=10) as r:
        return json.loads(r.read().decode())


def mod_post(path, payload):
    req = urllib.request.Request(
        f"{MOD}{path}", data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with _opener.open(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"error": f"http_{e.code}"}
    except (urllib.error.URLError, OSError) as e:
        print(f"[mod unreachable] {path}: {e}")
        return {"error": "mod_unreachable"}


def say(text):
    print(f"[TB says] {text}")
    mod_post("/say", {"text": text})


# ---------------- event channel (game ↔ agent, WebSocket on /ws) ----------------
# The mod pushes events (player chat, nav_done, ...) so we react instantly instead of polling.
# Bidirectional: ws_send() can push low-latency messages back to the game (e.g. interrupts) without
# an HTTP round-trip. A background thread holds the connection and drops parsed events into _events;
# instructions are split into _instructions for next_instruction().
WS_URL = MOD.replace("http://", "ws://").replace("https://", "wss://") + "/ws"
_events = queue.Queue()
_instructions = queue.Queue()
_ws = None            # live connection for ws_send()
_ws_lock = threading.Lock()


def ws_send(type_, data=None):
    """Push a message game-ward over the WebSocket (agent → game). Best-effort."""
    with _ws_lock:
        if _ws is None:
            return False
        try:
            _ws.send(json.dumps({"type": type_, "data": data or {}}))
            return True
        except Exception:
            return False


def _ws_listener():
    global _ws
    while True:
        try:
            with ws_connect(WS_URL, open_timeout=10) as sock:
                with _ws_lock:
                    _ws = sock
                print("[ws] connected")
                for raw in sock:
                    try:
                        ev = json.loads(raw)
                    except Exception:
                        continue
                    et = ev.get("type")
                    if et == "hello":
                        continue
                    if et == "instruction":
                        txt = ev.get("data", {}).get("text")
                        if txt:
                            _instructions.put(txt)
                    elif et in ("hurt", "threat", "hazard", "world_event", "survival"):
                        print(f"[eye] {et} {ev.get('data', {})}")   # B-path salience events from the mod
                    _events.put(ev)
        except Exception as e:
            print(f"[ws] disconnected ({e}), retrying...")
        finally:
            with _ws_lock:
                _ws = None
        time.sleep(2)


def drain_events():
    """Non-blocking: return and clear all non-instruction events seen since last call."""
    out = []
    while True:
        try:
            out.append(_events.get_nowait())
        except queue.Empty:
            break
    return out


# ---------------- Terraria Wiki (terraria.wiki.gg MediaWiki API) ----------------
WIKI = "https://terraria.wiki.gg/api.php"


def _wiki_get(params):
    # external host: use the default opener (honours system proxy), NOT the mod's no-proxy opener
    url = WIKI + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "TerraBlind-agent/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def wiki_search(query, limit=5):
    d = _wiki_get({"action": "query", "list": "search", "srsearch": query,
                   "srlimit": limit, "format": "json"})
    return [{"title": s["title"], "snippet": re.sub(r"<[^>]+>", "", s["snippet"])}
            for s in d.get("query", {}).get("search", [])]


def wiki_page(title, max_chars=3500):
    d = _wiki_get({"action": "parse", "page": title, "prop": "text", "format": "json",
                   "disablelimitreport": 1, "disableeditsection": 1, "redirects": 1})
    if "parse" not in d:
        return {"error": "not_found", "title": title}
    h = d["parse"]["text"]["*"]
    h = re.sub(r"<style.*?</style>", "", h, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", h)
    t = html.unescape(t)
    t = re.sub(r"\[\s*edit\s*\]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return {"title": d["parse"]["title"], "text": t[:max_chars]}


def next_instruction(block=False):
    """Next /tb text, or None. Prefers the WS-pushed queue; falls back to HTTP /instruction poll
    so a dropped WS connection never loses commands. If block=True, wait until one arrives."""
    while True:
        try:
            return _instructions.get_nowait()   # instant, pushed via WebSocket
        except queue.Empty:
            pass
        try:
            ins = mod_get("/instruction").get("instruction")   # fallback / catch anything SSE missed
        except Exception:
            ins = None
        if ins:
            return ins
        if not block:
            return None
        try:
            return _instructions.get(timeout=POLL_S)   # block on the pushed queue
        except queue.Empty:
            continue


# ---------------- tools ----------------

TOOLS = [
    {"type": "function", "function": {
        "name": "get_state",
        "description": "获取当前游戏状态快照:玩家血量/魔力/位置(像素,除以16得到格坐标)/速度/biome/背包装备。用它确认自己在哪、身上有什么。",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "wiki_search",
        "description": "搜 Terraria 官方 wiki(terraria.wiki.gg),返回匹配的页面标题+摘要。**不确定的游戏知识一律查 wiki,别凭记忆瞎说**——配方、掉落、boss 召唤条件、物品用途、进度门槛都查。查到标题后用 wiki_page 读正文。",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "搜索词(英文最准,如 'King Slime' / 'Hellstone Bar')"}},
            "required": ["query"],
        },
    }},
    {"type": "function", "function": {
        "name": "wiki_page",
        "description": "读 Terraria wiki 某个页面的正文(纯文本,含数据表如掉落率/伤害/配方)。title 用 wiki_search 返回的准确标题。",
        "parameters": {
            "type": "object",
            "properties": {"title": {"type": "string", "description": "页面标题(准确,如 'King Slime')"}},
            "required": ["title"],
        },
    }},
    {"type": "function", "function": {
        "name": "item_info",
        "description": "查背包里某个物品的详细信息(描述tooltip + 类型标志:武器伤害/镐力/放置物createTile/是否消耗品/回血等)。**同名或看不懂的物品别猜别反复问玩家,用这个查一眼就懂**(比如 BOMB 召唤妖精 vs 炸弹摧毁图格,靠 tooltip 分清)。给 slot(槽位号)或 name(物品名)。",
        "parameters": {
            "type": "object",
            "properties": {
                "slot": {"type": "integer", "description": "物品栏槽位号(0-based)"},
                "name": {"type": "string", "description": "物品名(和 slot 二选一)"},
            },
        },
    }},
    {"type": "function", "function": {
        "name": "find_biome",
        "description": "整张地图可读,所以'找丛林/雪地/地牢'不是探索问题,是查询问题。给一个 biome 名,返回它的中心可站坐标 {found,x,y,count}。支持:jungle/snow/desert/dungeon/corruption/crimson/hallow。找到坐标后直接 nav_to 过去。",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "biome 名,如 'jungle'"}},
            "required": ["name"],
        },
    }},
    {"type": "function", "function": {
        "name": "find_descent",
        "description": "找某 biome '下地狱代价最低'的地表主入口(main entrance)。不是逐列扫——用多源 Dijkstra 从地狱层整体向上流,顺着真实洞穴形状算代价,S形洞口从顶部进也算得出来。返回 {found,x,y,cost}。要速降地狱时先用它拿入口,再 nav_to 过去。biome 名同 find_biome。",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "biome 名,如 'jungle'"}},
            "required": ["name"],
        },
    }},
    {"type": "function", "function": {
        "name": "descent_route",
        "description": "在 find_descent 基础上,把'主入口→地狱'整条路线画进游戏画面(青色主线,持续2分钟),并列出绕路可及的箱子(金)和生命水晶(粉),真实支线路径相连。两档范围:挖<=dig_max且走<=walk_max → tier=main(顺手必捡);挖<=dig_max2且走<=walk_max2 → tier=optional(值不值你判断);再远不列。返回 {found,entrance,cost,line_len,treasures:[{x,y,kind,tier,line_x,line_y,dig,walk}]},dig/walk 是实际要挖/走的格数,line_x/line_y 是接驳点。规划'下地狱顺路搜刮'先调它。",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "biome 名,如 'jungle'"},
                           "dig_max": {"type": "integer", "description": "main档挖掘格数上限,默认20"},
                           "walk_max": {"type": "integer", "description": "main档移动格数上限,默认60"},
                           "dig_max2": {"type": "integer", "description": "optional档挖掘上限,默认50"},
                           "walk_max2": {"type": "integer", "description": "optional档移动上限,默认120"}},
            "required": ["name"],
        },
    }},
    {"type": "function", "function": {
        "name": "tile_names",
        "description": "查 find_tiles 能用的方块名。给一个关键词(英文,如 'heart'/'chest'/'altar'),返回所有含该词的原版 TileID 名。找方块前先用它确认准确名字,别猜。",
        "parameters": {
            "type": "object",
            "properties": {"q": {"type": "string", "description": "关键词(英文子串),留空列全部"}},
        },
    }},
    {"type": "function", "function": {
        "name": "find_tiles",
        "description": "在玩家周围找最近的某类方块,按距离排序返回格坐标。name 用原版 TileID 精确名(不确定就先 tile_names 查)。找 Containers(箱子)时每个结果带 kind 字段(箱子种类名,如 Chest=普通木箱/Gold Chest/Ivy Chest 常春藤箱/Ice Chest…)。**要特定种类的箱子时,把 n 设大(比如20),从返回列表里筛出 kind 匹配的那个再挑最近**——因为按距离排序时想要的种类可能排在很多其他箱子后面,n 太小会漏掉。找到后 nav_to 到旁边再 interact 开箱。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "TileID 精确名,如 'Iron'"},
                "n": {"type": "integer", "description": "返回数量,默认5"},
                "max_dist": {"type": "integer", "description": "搜索半径(格),默认300"},
            },
            "required": ["name"],
        },
    }},
    {"type": "function", "function": {
        "name": "nav_to",
        "description": "用 Bellman 寻路走/跳/挖/搭桥到目标格坐标。阻塞直到到达、失败或超时,返回结果。失败带原因码(walled_in/loop_unresolved/timeout等)——如实告诉玩家并考虑替代方案。可选 greed:沿途收集白名单(TileID 名数组,如 [\"Containers\",\"Heart\"])——赶路时每隔几秒扫附近,发现白名单目标就顺路捡了(开箱/挖掉)再继续赶路;够不着的自动放弃不纠缠。长途赶路+要沿途搜刮时用它。",
        "parameters": {
            "type": "object",
            "properties": {"x": {"type": "integer"}, "y": {"type": "integer"},
                           "greed": {"type": "array", "items": {"type": "string"},
                                     "description": "沿途收集的 TileID 名,如 Containers/Heart"}},
            "required": ["x", "y"],
        },
    }},
    {"type": "function", "function": {
        "name": "mine",
        "description": "从玩家位置向某方向朝目标格挖掘。立即返回;用 get_state 看进度。先 nav_to 到矿旁再挖。",
        "parameters": {
            "type": "object",
            "properties": {
                "dir": {"type": "string", "enum": ["left", "right", "up", "down"]},
                "target_x": {"type": "integer"}, "target_y": {"type": "integer"},
            },
            "required": ["dir", "target_x", "target_y"],
        },
    }},
    {"type": "function", "function": {
        "name": "use_item",
        "description": "对着一个格坐标使用背包里某个槽位的道具——**一步完成**:自动切槽位+瞄准+使用,并等到动作结束才返回。镐挖、斧砍树、剑砍、放方块、扔炸弹、用魔杖、喝药都走这个。slot 直接抄 get_state 里那个物品的 slot 字段。x,y 给大概位置即可:砍树/挖矿会自动吸附到最近的树干根部/可挖格,不用你算准。返回 outcome:removed=目标已消失(树倒了/矿挖掉了,成功);no_progress=一下都没啃动,看 reason:reason=tool_weak 是镐/斧不够硬(换更好的);reason=blocked 是上方压着树或箱子(原版不许抽走支撑,先清掉上方那格,换镐没用);timeout=在啃但没啃完(方向对,加大 duration_ticks 再来);n/a=非采集类道具(放置/扔/喝,正常)。采集类务必先 find_tiles 拿真实坐标,别自己编。道具有射程,先 nav 到旁边。",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "目标格x"},
                "y": {"type": "integer", "description": "目标格y"},
                "slot": {"type": "integer", "description": "物品栏槽位号(0-based)"},
                "duration_ticks": {"type": "integer", "description": "持续使用的帧数,默认30(约0.5秒);连续挖/放要大一些"},
            },
            "required": ["x", "y", "slot"],
        },
    }},
    {"type": "function", "function": {
        "name": "interact",
        "description": "与一个格坐标上的方块交互:开箱子、开门、按机关等(相当于右键那个方块)。先 nav_to 到方块旁边(交互有距离限制)。开箱后用 get_state 看背包变化确认掏到了什么。",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "方块格x"},
                "y": {"type": "integer", "description": "方块格y"},
            },
            "required": ["x", "y"],
        },
    }},
    {"type": "function", "function": {
        "name": "fight",
        "description": "用当前手持武器持续攻击附近最近的敌人(max_dist 格内自动锁定、追打)。打怪本质就是这个。先确保手上拿的是武器(get_state 看 selected_slot / 用 use_item 前先切槽)。这个工具会阻塞打一阵子并报告,期间玩家也能打断。清场或没敌人了就会停。",
        "parameters": {
            "type": "object",
            "properties": {
                "max_dist": {"type": "integer", "description": "锁敌半径(格),默认25"},
                "seconds": {"type": "number", "description": "打多久(秒),默认10;还有敌人可以再调一次"},
            },
        },
    }},
    {"type": "function", "function": {
        "name": "loot_all",
        "description": "把当前【已打开】的箱子里的东西全部掏进背包。必须先 interact 开箱,再 loot_all。",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "craft",
        "description": "合成一个物品(按名字)。需要站在对应工作台/熔炉旁边、材料足够,否则失败。失败时会返回当前能合成的物品列表(available_names),据此判断缺工作台还是缺材料。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "物品名(英文,如 'Iron Pickaxe')"},
                "amount": {"type": "integer", "description": "数量,默认1"},
            },
            "required": ["name"],
        },
    }},
    {"type": "function", "function": {
        "name": "ask",
        "description": "有疑问、需要玩家拍板时,用这个问玩家一个问题,然后【阻塞等待】玩家的回答(玩家用 /tb 回)。返回玩家的原话。任务不中断——拿到答案就在同一个任务里继续干。别为了省事自己瞎猜;也别把该问的做成结束回合让玩家重新发指令。",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "问玩家的话,中文"}},
            "required": ["question"],
        },
    }},
    {"type": "function", "function": {
        "name": "say",
        "description": "对玩家说话(中文,简短,像队友)。开始/关键进展/完成/失败都说一句。这不是提问——不需要回答用 say,需要回答用 ask。",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    }},
]


# ---- action-carries-state: every action returns the tiny slice of world needed to decide the NEXT step, so the
# ---- model never spends a whole RPM-limited call on a bare get_state or a delta re-check. ----

def _inv_map(state):
    """name -> total stack, from a /state snapshot's items array."""
    m = {}
    for it in (state.get("equipment", {}).get("items", []) or []):
        n = it.get("name")
        if n:
            m[n] = m.get(n, 0) + it.get("stack", 0)
    return m

def _slim(state):
    """The minimum a decision needs after an action: where am I, am I hurt."""
    p = state.get("player", {})
    pos = p.get("pos", {})
    return {"pos": {"x": round(pos.get("x", 0) / 16), "y": round(pos.get("y", 0) / 16)},
            "hp": p.get("hp"), "on_ground": p.get("on_ground")}

def _inv_snapshot():
    return _inv_map(mod_get("/state"))

def with_result(base, prev_inv):
    """Attach post-action slim state + inventory delta (got/lost) to a tool result, so the model has what it needs
    to decide the next step WITHOUT a separate get_state call."""
    st = mod_get("/state")
    now = _inv_map(st)
    got = {n: now[n] - prev_inv.get(n, 0) for n in now if now[n] - prev_inv.get(n, 0) > 0}
    lost = {n: prev_inv.get(n, 0) - now.get(n, 0) for n in prev_inv if prev_inv[n] - now.get(n, 0) > 0}
    base = dict(base)
    base["state"] = _slim(st)
    if got:
        base["got"] = got
    if lost:
        base["lost"] = lost
    return json.dumps(base, ensure_ascii=False)


def _greed_collect(cat, t):
    """One side-trip for whitelisted loot while traveling: chest → open+loot, anything else → pick it out.
    Fails FAST — can't reach or can't dent means give up and move on; the journey matters more than any
    single trinket. Returns an interrupted-result dict if the player spoke mid-trip (caller hands it up)."""
    tx, ty = t["x"], t["y"]
    say(f"顺路捡:{t.get('kind') or cat}({tx},{ty})")
    nav = json.loads(run_tool("nav_to", {"x": tx, "y": ty}))   # no greed here — side-trips don't nest
    if nav.get("status") == "interrupted":
        return nav
    if not nav.get("done") and nav.get("status") != "done":
        return None
    if cat == "Containers":
        run_tool("interact", {"x": tx, "y": ty})
        run_tool("loot_all", {})
    else:
        slot = _best_tool_slot("pick")
        run_tool("use_item", {"x": tx, "y": ty, "strict": True,
                              "slot": slot if slot is not None else -1, "duration_ticks": 0})
    return None


def run_tool(name, args):
    if name == "get_state":
        return json.dumps(mod_get("/state"), ensure_ascii=False)
    if name == "wiki_search":
        try:
            return json.dumps({"results": wiki_search(args["query"])}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"wiki_unreachable: {e}"})
    if name == "wiki_page":
        try:
            return json.dumps(wiki_page(args["title"]), ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"wiki_unreachable: {e}"})
    if name == "item_info":
        payload = {}
        if "slot" in args:
            payload["slot"] = args["slot"]
        if "name" in args:
            payload["name"] = args["name"]
        return json.dumps(mod_post("/item_info", payload))
    if name == "find_biome":
        return json.dumps(mod_post("/find_biome", {"name": args["name"]}))
    if name == "find_descent":
        return json.dumps(mod_post("/find_descent", {"name": args["name"]}))
    if name == "descent_route":
        req = {"name": args["name"]}
        for k in ("dig_max", "walk_max", "dig_max2", "walk_max2"):
            if args.get(k):
                req[k] = int(args[k])
        return json.dumps(mod_post("/descent_route", req))
    if name == "tile_names":
        return json.dumps(mod_post("/tile_names", {"q": args.get("q", "")}))
    if name == "find_tiles":
        return json.dumps(mod_post("/find_tiles", {
            "name": args["name"], "n": args.get("n", 5), "max_dist": args.get("max_dist", 300)}))
    if name == "nav_to":
        req = {"gx": args["x"], "gy": args["y"]}
        if args.get("exact"):   # mining: goal is a solid ore the body can't stand on — dig a shaft down to it
            req["exact"] = True
        greed = [g for g in (args.get("greed") or []) if isinstance(g, str)]
        visited = set()          # loot we already grabbed or gave up on — never circle back
        while True:
            r = mod_post("/nav_recede", req)
            if not r.get("ok"):
                return json.dumps(r)
            deadline = time.monotonic() + NAV_TIMEOUT_S
            last_report = time.monotonic()
            last_greed = time.monotonic()
            resume = False
            while time.monotonic() < deadline:
                time.sleep(0.5)
                # INTERRUPTIBLE: a new /tb while walking means the player wants to intervene.
                # Stop nav, hand the interruption + where-we-stopped back to the LLM to re-decide.
                interrupt = next_instruction(block=False)
                if interrupt:
                    mod_post("/nav_recede_stop", {})
                    st = mod_get("/state")
                    pos = st.get("player", {}).get("pos", {})
                    return json.dumps({"done": False, "status": "interrupted",
                                       "player_said": interrupt,
                                       "stopped_at_px": pos})
                d = mod_get("/nav_recede_done")
                if d.get("done") or d.get("status") == "failed":
                    d = dict(d)
                    d["state"] = _slim(mod_get("/state"))   # where did we end up — no separate get_state needed
                    return json.dumps(d, ensure_ascii=False)
                # GREED: while traveling, scan for whitelisted loot nearby; grab it, then resume the journey
                # (receding nav restarts from wherever we stand — the goal field is cached, resume is free).
                if greed and time.monotonic() - last_greed >= 3.0:
                    last_greed = time.monotonic()
                    hit = None
                    for cat in greed:
                        rr = mod_post("/find_tiles", {"name": cat, "n": 5, "max_dist": 25})
                        for t in (rr.get("tiles") or []):
                            if (t["x"], t["y"]) not in visited:
                                hit = (cat, t); break
                        if hit:
                            break
                    if hit:
                        cat, t = hit
                        visited.add((t["x"], t["y"]))
                        mod_post("/nav_recede_stop", {})
                        intr = _greed_collect(cat, t)
                        if intr:
                            return json.dumps(intr)   # player spoke during the side-trip — hand it up
                        resume = True
                        break
                # periodic progress note so the player isn't staring at a black screen
                if time.monotonic() - last_report >= NAV_REPORT_S:
                    last_report = time.monotonic()
                    st = mod_get("/state")
                    pos = st.get("player", {}).get("pos", {})
                    px, py = pos.get("x", 0) / 16, pos.get("y", 0) / 16
                    dist = abs(px - args["x"]) + abs(py - args["y"])
                    say(f"还在走,离目标还有约{int(dist)}格。")
            if resume:
                continue
            mod_post("/nav_recede_stop", {})
            return json.dumps({"done": False, "status": "timeout"})
    if name == "mine":
        return json.dumps(mod_post("/mine", {
            "dir": args["dir"], "target_wx": args["target_x"], "target_wy": args["target_y"]}))
    if name == "use_item":
        prev_inv = _inv_snapshot()
        dur = args.get("duration_ticks", 30)
        r = mod_post("/item_use", {
            "target_wx": args["x"], "target_wy": args["y"],
            "slot": args["slot"], "duration_ticks": dur,
            "strict": bool(args.get("strict"))})
        if not r.get("ok"):
            return json.dumps(r)
        # Wait for the real result. A collect target (chop/mine) ends by OBSERVING the world fact — "removed" (tile
        # gone) or "no_progress" (can't dent it) — the mod keeps swinging until then, so we poll until it's done, not
        # to a swing budget. A non-collect use (bomb/potion) has no result tile and ends at n/a on the mod's budget.
        # A generous safety cap only guards against a hang, it is NOT the completion condition.
        deadline = time.monotonic() + 60.0
        st = {"active": True, "outcome": "running"}
        while time.monotonic() < deadline:
            time.sleep(0.2)
            st = mod_get("/item_use_status")
            if not st.get("active"):
                break
        return with_result({"outcome": st.get("outcome"), "reason": st.get("reason"),
                             "snapped_to": {"x": st.get("snapped_wx"), "y": st.get("snapped_wy")},
                             "target": st.get("target")}, prev_inv)
    if name == "interact":
        prev_inv = _inv_snapshot()
        r = mod_post("/interact", {"tile_x": args["x"], "tile_y": args["y"]})
        return with_result(r, prev_inv)
    if name == "fight":
        max_dist = args.get("max_dist", 25)
        secs = float(args.get("seconds", 10))
        mod_post("/fight", {"max_dist": max_dist})
        deadline = time.monotonic() + secs
        while time.monotonic() < deadline:
            time.sleep(0.5)
            interrupt = next_instruction(block=False)
            if interrupt:
                mod_post("/fight", {"active": False})
                return json.dumps({"status": "interrupted", "player_said": interrupt})
            if not mod_get("/fight_active").get("active"):
                return json.dumps({"status": "cleared", "note": "附近没有敌人了"})
        mod_post("/fight", {"active": False})
        return json.dumps({"status": "timeout", "note": "打了一阵,可能还有敌人"})
    if name == "loot_all":
        prev_inv = _inv_snapshot()
        r = mod_post("/loot_all", {})
        return with_result(r, prev_inv)
    if name == "craft":
        prev_inv = _inv_snapshot()
        r = mod_post("/craft", {"item_name": args["name"], "amount": args.get("amount", 1)})
        return with_result(r, prev_inv)
    if name == "ask":
        say(args["question"])
        answer = next_instruction(block=True)   # BLOCK the task until the player replies with /tb
        return json.dumps({"player_answer": answer})
    if name == "say":
        say(args["text"])
        return "ok"
    return json.dumps({"error": f"unknown tool {name}"})


# ---------------- agent loop ----------------

SYSTEM = """你是 TB,Terraria 里的 AI 二号玩家,和人类搭档。接到目标就自己分解、执行、有疑问问玩家、
拿答案继续,直到办成。你看不到画面,感官和手都是工具。

调用很贵(每分钟只能动几次),每次调用都要有用。省调用的铁律:
- 说话写进你回复的正文里,和动作同一轮发出——正文会自动转达给玩家。别单独调 say(那白烧一次)。只有纯聊天没动作时才用 say。
- 动作已带回结果:use_item/craft/interact/loot_all/nav_to 返回里就有 state(位置/hp)和 got/lost(物品增减)。绝不为"看一眼"或"复核"单独调 get_state。
- 想清楚一步到位,别试探。

行为:
- 说中文,简短,像队友。开始/完成/失败各交代一句(写正文里)。
- 拿不准就 ask 问玩家(目标模糊、要拍板),拿到答案继续。同名或陌生物品先 item_info 查清楚。
- 砍树、挖矿:先 find_tiles 拿真实坐标(tile 名不确定先 tile_names 查,别猜),再 use_item;看 outcome 判成败,no_progress 按 reason 换法,timeout 加时长。
- 寻路或动作失败,如实告诉玩家原因,提替代方案。
- 玩家能随时打断:工具返回 status=interrupted 时,先回应,再按新意思决定继续/改向/干别的。

知识:你的 Terraria 记忆不可靠。配方、掉落、数值、召唤条件一律 wiki_search + wiki_page 查官方 wiki。
只有"大方向怎么打"这类策略可以自己想。
"""


# ============================ 甲方案: plan-once + self-execute (LLM-Planner style) ============================
# The brain plans a whole flat action sequence in ONE call, the executor runs it with no LLM per step, and the brain
# is only woken again on failure/interruption. This is the RPM=10 survival strategy: brain calls track surprises,
# not steps. Matches LLM-Planner (arXiv 2212.04088): flat plan, objects grounded at execution time via placeholders,
# replanning on execution failure with completed-steps + current-state in the prompt.

PLANNER_SYSTEM = """你是 Terraria agent TB 的规划器。给你一个目标 + 当前现状,你一次性输出一条动作序列(JSON),
执行器会自己按序执行,不再回来问你,除非某步失败。所以要一次规划到位。

只输出 JSON:{"say":"给玩家的一句话","plan":[ 动作, 动作, ... ]}

每个动作是一个对象,op 是下面之一:
- {"op":"find","id":"t","what":"<TileID英文名,如Trees/Iron/Containers>","n":1}  在附近找最近的方块,结果存到 id
- {"op":"find_biome","id":"j","what":"jungle"}        全图找生物群系中心(jungle/snow/desert/dungeon/corruption/crimson/hallow)。**去远处的丛林/雪地/地牢用这个,别用 find**
- {"op":"nav","to":"$t.pos"}                          走到某坐标
- {"op":"use","at":"$t.pos","tool":"axe|pick|hammer","until":"removed","dur":80}  用工具作用于某格(砍/挖)
- {"op":"use","at":[x,y],"slot":N,"dur":30}          用背包某槽道具作用于某格(放置/扔炸弹到某处);slot 抄现状 items 的 slot 字段
- {"op":"use","slot":N,"dur":30}                      对自己用的道具(传送杖/喝药/召唤),不带 at
- {"op":"craft","name":"<中文物品名>","amount":N}     合成
- {"op":"interact","at":"$c.pos"}                     开箱/开门/机关
- {"op":"loot"}                                       捡光当前箱子
- {"op":"fight","max_dist":25,"seconds":10}           清怪
- {"op":"say","content":"..."}                        中途给玩家说一句(需要边做边解释时)
- {"op":"probe","id":"p","at":"$t.pos"}               查一格:有无背景墙、能否放平台/方块、是否空(結果存id)
- {"op":"measure","id":"m","at":"$t.pos"}             量连通块尺寸:树多高/矿多大/空腔多大(結果存id)

占位符:find 的结果用 $id.pos 在后续步引用(规划时坐标未知,执行到那步才填)。别自己编坐标。
前置条件自己判断:看现状背包,已有斧就别再规划找斧;缺什么就把补齐步骤也排进 plan。
tool:"axe"/"pick"/"hammer" 让执行器自动挑背包里最好的那把,你不用管 slot。
tile 名不确定就用常见的(树=Trees,铁矿=Iron,箱子=Containers)。plan 尽量短、直达目标。

你脑内的 Terraria 知识不可靠,只用手上的真实信息:
- 道具用途只信现状里它的 tooltip(括号那句),没写的机制就当没有。
- op 只从上面清单选;物品只用背包里真有的。
- 去远处生物群系用 find_biome 拿位置,别凭记忆报方位。
- 机制/配方不确定就先做能确定的,plan 短一点没关系。

只输出 JSON。"""


# ============================ FIND-CLASS TEMPLATE ============================
# Nearly every concrete Terraria task is "there's a thing in the world, go do something to it": chop tree, mine ore,
# go to a biome, open a chest, fight a mob. They ALL share ONE skeleton — locate → nav → act → repeat-until — and
# differ only in a handful of variables. So instead of letting the AI freely emit ops (where it hallucinates: bombs
# to clear a path, invents '探针'), the AI only FILLS THE VARIABLES; code runs the fixed skeleton. AI can't add
# steps, can't invent tools. One tiny AI call per goal instead of per step.

FIND_CLASSIFIER_SYSTEM = """把玩家的目标填成一张变量表(JSON),别的不做。这类目标的共同形状是:
「世界上有个东西,找到它→走过去→对它做点什么→重复到够」。只要目标是这个形状,就填表:

{"find_class": true,
 "what": "<找什么:TileID英文名如Trees/Iron/Containers,或biome名如jungle/snow/dungeon>",
 "how": "find" 或 "find_biome" 或 "find_descent",  // 近处方块find;远处生物群系find_biome;'主道/主入口/下地狱'用find_descent
 "act": "chop" | "mine" | "open" | "fight" | "none",  // 到了做什么:砍/挖/开箱/打/只是到达
 "count": <砍/挖/开几个目标,默认1>,
 "gather": "<仅当目标是'攒够某物品数量'时填,如 木材>=20;说'砍N棵/挖N个'用 count,别填 gather>",
 "filter": "<可选:筛选,如 Gold Chest>",
 "say": "给玩家的一句话"}

count 和 gather 二选一:数目标个数用 count,攒物品数量用 gather。别两个都填。
如果目标不是这个形状(比如合成装备、造房子、复杂多步),返回 {"find_class": false}。

判定:砍2棵树=what:Trees,act:chop,count:2(不填gather)。挖10铁=what:Iron,act:mine,count:10。
砍树直到木材够20=act:chop,gather:木材>=20(不填count)。去丛林=what:jungle,how:find_biome,act:none。
开金箱=what:Containers,act:open,filter:Gold Chest。tile名不确定就用常见的。只输出 JSON。"""


_ACT_TOOL = {"chop": "axe", "mine": "pick"}       # act → which tool kind to auto-pick


def classify_find(goal):
    """One tiny AI call: fill the find-class variable table, or {find_class:false} if the goal isn't this shape."""
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": FIND_CLASSIFIER_SYSTEM},
                      {"role": "user", "content": f"目标:{goal}\n\n现状:\n{slim_world_for_planner()}"}],
            response_format={"type": "json_object"},
        )
        u = getattr(resp, "usage", None)
        print(f"[classify] in={u.prompt_tokens} out={u.completion_tokens}" if u else "[classify]")
        d = json.loads(resp.choices[0].message.content)
        return d if d.get("find_class") else None
    except Exception as e:
        print(f"[classify error] {e}")
        return None


def run_find_template(spec):
    """Run the ONE find-class skeleton from a filled variable table — no AI, no hallucinated ops.
    locate → nav → act → repeat until count/gather met. Returns True if it handled the goal, False to fall back."""
    if spec.get("say"):
        say(spec["say"])
    what = spec.get("what")
    how = spec.get("how", "find")
    act = spec.get("act", "none")
    count = int(spec.get("count", 1) or 1)
    filt = (spec.get("filter") or "").strip().lower()
    biome = _biome_of(what)
    if biome:
        what = biome
        if how != "find_descent":     # descent routing must survive the biome auto-route
            how = "find_biome"

    done_count = 0            # targets actually completed (loop-exit counter, NOT a candidate index)
    skip = set()              # coords we couldn't reach → exclude on the next locate
    for _ in range(max(count, 1) + 5):
        # ---- LOCATE ---- always take the NEAREST not-yet-tried target. A completed target has vanished from the
        # world, so the next find naturally surfaces the next one; we only need to exclude the unreachable ones.
        if how == "find_descent":
            r = mod_post("/find_descent", {"name": what})
            if not r.get("found"):
                say(f"没找到{what}的主入口。"); return True
            tx, ty = r["x"], r["y"]
        elif how == "find_biome":
            r = mod_post("/find_biome", {"name": what})
            if not r.get("found"):
                say(f"没找到{what}。"); return True
            tx, ty = r["x"], r["y"]
        else:
            r = mod_post("/find_tiles", {"name": what, "n": 20, "max_dist": 400})
            tiles = r.get("tiles") or []
            if filt:
                tiles = [t for t in tiles if filt in str(t.get("kind", "")).lower()] or tiles
            tiles = [t for t in tiles if (t["x"], t["y"]) not in skip]
            if not tiles:
                say(f"附近没有{('可到达的' if skip else '')}{what}了。"); return True
            tx, ty = tiles[0]["x"], tiles[0]["y"]
        print(f"[tmpl] locate → ({tx},{ty})")

        # ---- NAV ---- (assume nav works, per current scope). MINING navigates EXACT: the ore sits inside solid rock
        # the body can't stand on, so nav digs a shaft straight down to that tile — arrival IS the ore mined out, no
        # separate swing needed. Everything else navigates to a standable cell beside the target, then acts.
        nav = json.loads(run_tool("nav_to", {"x": tx, "y": ty, "exact": act == "mine"}))
        print(f"[tmpl] nav → {nav.get('status')} @ {nav.get('state',{}).get('pos')}")
        if nav.get("status") in ("walled_in", "loop_unresolved", "timeout") or nav.get("status") == "failed":
            skip.add((tx, ty))      # unreachable → exclude it and try the next-nearest
            continue

        # ---- ACT ----  ONE target's completion is the observed world fact: the tile is REMOVED.
        if act == "mine":
            # exact-nav dug a shaft to the nearest ore (it's gone now). The body now stands INSIDE the vein, so a
            # whole cluster of the same ore sits within reach. Batch-mine every reachable one from this stance —
            # like a human clearing a pocket before moving on — instead of navigating to each ore separately.
            done_count += 1                       # the shaft-target ore itself
            reach = mod_get("/mine_reach")
            if not reach.get("error"):
                mslot = _best_tool_slot("pick")
                mined_here = 0
                # re-find same-type ores, keep only those inside the reach rectangle, mine each until removed
                rr = mod_post("/find_tiles", {"name": what, "n": 40, "max_dist": 60})
                for t in (rr.get("tiles") or []):
                    ox, oy = t["x"], t["y"]
                    if not (reach["lx"] <= ox <= reach["hx"] and reach["ly"] <= oy <= reach["hy"]):
                        continue
                    # strict: never let snap re-aim to some random rock when this exact ore is gone
                    res = json.loads(run_tool("use_item", {"x": ox, "y": oy, "strict": True,
                                                           "slot": mslot if mslot is not None else -1, "duration_ticks": 0}))
                    out, why = res.get("outcome"), res.get("reason") or ""
                    print(f"[tmpl] mine ({ox},{oy}) → {out}{('/' + why) if why else ''} got={res.get('got')}")
                    if out == "removed":
                        done_count += 1; mined_here += 1
                        if done_count >= count:
                            break
                    elif why == "out_of_reach":
                        # mining below moved the body (fell into own hole) → the whole batch's stance is stale.
                        # Stop swinging at ghosts; the outer loop re-locates from where we actually stand now.
                        break
                    # target_gone → already vanished, try the next candidate
                print(f"[tmpl] mine batch → +{mined_here} in reach [{reach['lx']},{reach['ly']}..{reach['hx']},{reach['hy']}]")
            if done_count >= count:
                say(f"搞定,{done_count}个。"); return True
            continue                              # cluster cleared → locate the next vein
        elif act == "chop":
            # tree: stand beside it, swing the axe until the trunk is REMOVED (or no_progress = can't dent it).
            slot = _best_tool_slot(_ACT_TOOL[act])
            res = json.loads(run_tool("use_item", {"x": tx, "y": ty,
                                                   "slot": slot if slot is not None else -1, "duration_ticks": 0}))
            print(f"[tmpl] act {act} → outcome={res.get('outcome')} snapped={res.get('snapped_to')} got={res.get('got')}")
            if res.get("outcome") == "no_progress":
                say(f"这个砍不动({res.get('reason')})。"); return True
            if res.get("outcome") != "removed":
                # NOT removed (timeout/n/a/…) means this target did NOT actually fall — don't count it, skip & retry.
                skip.add((tx, ty)); continue
        elif act == "open":
            run_tool("interact", {"x": tx, "y": ty})
            run_tool("loot_all", {})
        elif act == "fight":
            run_tool("fight", {"max_dist": 25, "seconds": 10})
        # act == "none" → arriving was the goal

        done_count += 1
        # ---- DONE? ----  count vs gather are mutually exclusive. If the user gave an explicit count (>1), that wins
        # even if the AI also (wrongly) filled gather — "砍2棵" must not stop because inventory already had wood.
        # gather only applies when no explicit count was given (count defaulted to 1).
        gather = (spec.get("gather") or "").strip()
        if gather and count <= 1:
            m = re.match(r"(.+?)\s*>=\s*(\d+)", gather)
            if m:
                name, need = m.group(1).strip(), int(m.group(2))
                have = _inv_snapshot().get(name, 0)
                if have >= need:
                    say(f"{name}够了({have})。"); return True
                continue
        if done_count >= count:
            say(f"搞定,{done_count}个。"); return True
    say(f"弄完了({done_count}个)。")
    return True


def plan_goal(goal, fail_ctx=None):
    """ONE planning call → flat action sequence. fail_ctx (dict) carries replanning context after a failed step.
    Returns (say:str, plan:list) or (None, []) on error."""
    state = slim_world_for_planner()
    user = f"目标:{goal}\n\n现状:\n{state}"
    if fail_ctx:
        user += (f"\n\n上次执行到第{fail_ctx['step']}步 {fail_ctx['op']} 失败:{fail_ctx['result']}\n"
                 f"已完成:{fail_ctx['done']}\n给一条修复计划接着干(别从头)。")
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": PLANNER_SYSTEM},
                      {"role": "user", "content": user}],
            response_format={"type": "json_object"},
        )
        u = getattr(resp, "usage", None)
        print(f"[plan] in={u.prompt_tokens} out={u.completion_tokens}" if u else "[plan]")
        d = json.loads(resp.choices[0].message.content)
        plan = d.get("plan")
        if isinstance(plan, list):
            return d.get("say", ""), plan
    except Exception as e:
        print(f"[planner error] {e}")
    return None, []


def slim_world_for_planner():
    """Compact starting state for the planner: position, inventory (name/slot/stack + tool stats), biome, key world
    flags. This IS the 'observed objects' the LLM-Planner prompt needs — so the plan is grounded from the first call
    and the brain never spends a step just to look around."""
    st = mod_get("/state")
    p = st.get("player", {})
    pos = p.get("pos", {})
    items = []
    tip_budget = 8   # cap how many tooltips we fetch, so a full backpack can't blow up tokens
    for it in (st.get("equipment", {}).get("items", []) or []):
        tag = ""
        if it.get("axe"): tag = f" axe{it['axe']}"
        elif it.get("pick"): tag = f" pick{it['pick']}"
        elif it.get("hammer"): tag = f" hammer{it['hammer']}"
        line = f"[{it.get('slot')}]{it.get('name')}x{it.get('stack')}{tag}"
        # Attach the GAME'S OWN tooltip for functional items (wands/potions/hooks/summons land in misc/consumable) —
        # the brain has no reliable memory of what "和谐杖" does and will invent "needs mana". The vanilla tooltip is
        # authoritative and un-inventable. Tools/blocks are self-evident from tag, skip them.
        cat = it.get("category", "misc")
        if tip_budget > 0 and cat in ("misc", "consumable"):
            info = mod_post("/item_info", {"slot": it.get("slot")})
            tip = (info.get("tooltip") or "").strip()
            if tip:
                line += f"（{tip[:80]}）"
                tip_budget -= 1
        items.append(line)
    w = st.get("world", {})
    return (f"位置格({round(pos.get('x',0)/16)},{round(pos.get('y',0)/16)}) hp{p.get('hp')} biome={p.get('biome')} "
            f"{'夜' if not w.get('day') else '昼'}{' 血月' if w.get('blood_moon') else ''}\n"
            f"背包:{', '.join(items)}")


_BIOME_ALIASES = {
    "jungle": "jungle", "junglegrass": "jungle", "lihzahrdbrick": "jungle", "丛林": "jungle",
    "snow": "snow", "ice": "snow", "雪": "snow", "雪原": "snow",
    "desert": "desert", "沙漠": "desert",
    "dungeon": "dungeon", "地牢": "dungeon",
    "corruption": "corruption", "腐化": "corruption", "corrupt": "corruption",
    "crimson": "crimson", "猩红": "crimson",
    "hallow": "hallow", "神圣": "hallow",
}

def _biome_of(what):
    """If a find target names a biome (however the planner spelled it), return the find_biome key; else ''."""
    return _BIOME_ALIASES.get(str(what).strip().lower(), "")


def _unresolved(ref):
    """A placeholder like $jungle.pos couldn't be resolved = that find/find_biome never succeeded. Say so plainly so
    the brain replans by FINDING it first, instead of hallucinating that it was already found."""
    rid = str(ref)[1:].split(".")[0] if str(ref).startswith("$") else ref
    return json.dumps({"error": "not_found_yet",
                       "detail": f"引用 {ref} 但 '{rid}' 从没被成功找到过——先用能定位它的 find/find_biome 拿到坐标,别假设已找到"},
                      ensure_ascii=False)


def resolve_arg(v, results):
    """Replace a '$id.field' placeholder with its actual value from a completed step's result.
    Non-placeholder values (numbers, lists, plain strings) pass through untouched."""
    if isinstance(v, str) and v.startswith("$"):
        ref = v[1:]                       # e.g. "t.pos"
        parts = ref.split(".")
        cur = results.get(parts[0])
        for p in parts[1:]:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(p)
        return cur
    return v


def _best_tool_slot(kind):
    """Pick the strongest axe/pick/hammer in the inventory so the planner never has to name a slot."""
    st = mod_get("/state")
    best, best_slot = -1, None
    for it in (st.get("equipment", {}).get("items", []) or []):
        v = it.get(kind, 0)
        if v > best:
            best, best_slot = v, it.get("slot")
    return best_slot


def exec_op(op, results):
    """Map ONE plan op to run_tool, resolving placeholders. Returns the raw json-string result. Raises on a
    structurally bad op (missing resolved coord) so the executor can treat it as a failure to replan on."""
    o = op.get("op")
    if o == "say":
        say(op.get("content") or op.get("text") or "")
        return json.dumps({"ok": True})
    # The planner keeps reaching for `find` on a biome (JungleGrass/LihzahrdBrick) even when told to use find_biome —
    # a local tile scan can't see a far biome, so it returns empty and the plan dies. Code-level correction: if the
    # target is a known biome, route to find_biome regardless of which op the planner picked. Don't rely on the prompt.
    if o in ("find", "find_biome"):
        biome = _biome_of(op.get("what", ""))
        if biome:
            o = "find_biome"
            op = {**op, "what": biome}
    if o == "find":
        out = run_tool("find_tiles", {"name": op["what"], "n": op.get("n", 1), "max_dist": op.get("max_dist", 200)})
        d = json.loads(out)
        tiles = d.get("tiles") or []
        if not tiles:
            # empty find must FAIL loudly (not silently leave the placeholder unresolved) so the brain replans with
            # a better approach — e.g. a far target like "去丛林" needs find_biome, not a local find_tiles scan.
            return json.dumps({"error": "not_found", "what": op.get("what")}, ensure_ascii=False)
        results[op.get("id", "_")] = {"pos": {"x": tiles[0]["x"], "y": tiles[0]["y"]}, "tiles": tiles}
        return out
    if o == "find_biome":
        out = run_tool("find_biome", {"name": op["what"]})
        d = json.loads(out)
        if not d.get("found"):
            return json.dumps({"error": "biome_not_found", "what": op.get("what")}, ensure_ascii=False)
        results[op.get("id", "_")] = {"pos": {"x": d["x"], "y": d["y"]}}
        return out
    if o == "nav":
        pos = resolve_arg(op["to"], results)
        if not pos:
            return _unresolved(op["to"])
        x, y = (pos["x"], pos["y"]) if isinstance(pos, dict) else (pos[0], pos[1])
        return run_tool("nav_to", {"x": x, "y": y})
    if o == "use":
        # self-use items (teleport wand / potion / summon) act on the player, no target coord needed → x=y=-1.
        at = resolve_arg(op["at"], results) if op.get("at") is not None else None
        if op.get("at") is not None and not at:
            return _unresolved(op["at"])
        x, y = (-1, -1) if at is None else ((at["x"], at["y"]) if isinstance(at, dict) else (at[0], at[1]))
        slot = op.get("slot")
        if slot is None and op.get("tool"):
            slot = _best_tool_slot(op["tool"])
        return run_tool("use_item", {"x": x, "y": y, "slot": slot if slot is not None else -1,
                                     "duration_ticks": op.get("dur", 60)})
    if o == "craft":
        return run_tool("craft", {"name": op["name"], "amount": op.get("amount", 1)})
    if o == "interact":
        at = resolve_arg(op["at"], results)
        if not at:
            return _unresolved(op["at"])
        x, y = (at["x"], at["y"]) if isinstance(at, dict) else (at[0], at[1])
        return run_tool("interact", {"x": x, "y": y})
    if o == "loot":
        return run_tool("loot_all", {})
    if o == "fight":
        return run_tool("fight", {"max_dist": op.get("max_dist", 25), "seconds": op.get("seconds", 10)})
    if o == "probe":
        at = resolve_arg(op["at"], results)
        if not at:
            return json.dumps({"error": "unresolved_coord", "at": op["at"]})
        x, y = (at["x"], at["y"]) if isinstance(at, dict) else (at[0], at[1])
        out = mod_post("/probe_cell", {"x": x, "y": y})
        if op.get("id"):
            results[op["id"]] = out
        return json.dumps(out, ensure_ascii=False)
    if o == "measure":
        at = resolve_arg(op["at"], results)
        if not at:
            return json.dumps({"error": "unresolved_coord", "at": op["at"]})
        x, y = (at["x"], at["y"]) if isinstance(at, dict) else (at[0], at[1])
        out = mod_post("/measure", {"x": x, "y": y})
        if op.get("id"):
            results[op["id"]] = out
        return json.dumps(out, ensure_ascii=False)
    return json.dumps({"error": f"unknown_op {o}"})


# an op result is a FAILURE (→ wake the brain) if it carries these signals. removed/done/cleared/crafted = success.
_FAIL_SIGNALS = ("error", "no_progress", "walled_in", "loop_unresolved", "timeout", "unresolved_coord")


def op_failed(result_str):
    try:
        d = json.loads(result_str)
    except Exception:
        return False
    if d.get("outcome") in ("no_progress", "timeout"):
        return True
    if d.get("status") in ("failed", "walled_in", "loop_unresolved", "timeout"):
        return True
    if "error" in d:
        return True
    return False


def drain_stale_instructions():
    """A /tb is delivered on BOTH channels (WS push + HTTP queue). The main loop consumes one copy to start this
    goal; the twin left in mod's HTTP queue would otherwise be caught as a phantom interrupt on the first op. Drain
    it once here so only instructions that arrive AFTER planning count as real interrupts."""
    try:
        mod_get("/instruction")          # pop the duplicate HTTP copy of the goal we're starting
    except Exception:
        pass
    while True:                          # clear any WS-queued twin too
        try:
            _instructions.get_nowait()
        except queue.Empty:
            break


def run_goal(goal):
    """Top loop. FAST PATH: if the goal is a find-class task (chop/mine/goto/open/fight), the AI just fills a variable
    table and code runs the fixed skeleton — no hallucinated ops. FALLBACK: 甲方案 free planning for everything else."""
    drain_stale_instructions()

    spec = classify_find(goal)
    if spec:
        # keyword routing in CODE, not prompt-trust: 主道/主入口/下地狱 means the descent-cost main entrance
        # (find_descent), never the nearest-edge surface tile find_biome would return.
        if re.search(r"主道|主入口|下地狱|速降|main", goal, re.I):
            spec["how"] = "find_descent"
        print(f"[find-template] {spec}")
        run_find_template(spec)
        return

    fail_ctx = None
    for attempt in range(3):   # initial plan + up to 2 replans, then give up (save RPM, ask player)
        say_txt, plan = plan_goal(goal, fail_ctx)
        if not plan:
            say("我一时没想好怎么做,你能说得具体点吗?")
            return
        if say_txt:
            say(say_txt)
        print(f"[plan] {len(plan)} ops: {[o.get('op') for o in plan]}")

        results, done = {}, []
        for i, op in enumerate(plan):
            # interruptible between ops
            interrupt = next_instruction(block=False)
            if interrupt:
                say("好,先停,你说。")
                _pending_instructions.append(interrupt)
                return
            print(f"[op {i+1}/{len(plan)}] {op}")
            try:
                out = exec_op(op, results)
            except Exception as e:
                out = json.dumps({"error": str(e)})
            print(f"[op<] {out[:200]}")
            if op_failed(out):
                fail_ctx = {"step": i + 1, "op": op.get("op"), "result": out[:200], "done": done}
                break
            done.append(op.get("op"))
        else:
            return   # whole plan ran without failure — done
    say("试了几次没成,这个我先卡住了,你看看?")


_pending_instructions = []   # instructions caught mid-plan, re-fed to the main loop


# tool results that are large and only matter fresh — old copies get stubbed out of the sent history
# so token usage doesn't balloon (a full get_state is several KB; 3 of them in history = huge input).
_BULKY_TOOLS = {"get_state", "find_tiles", "wiki_page", "item_info"}
_STUB = "[旧结果已省略,需要就重新查]"


def compact_for_send(history):
    """Return a copy of history where every BULKY tool result EXCEPT the last one is stubbed. The model
    only needs the freshest state; stale multi-KB blobs are pure token cost."""
    # map assistant tool_call_id -> tool name, to know which tool results are bulky
    id2name = {}
    for m in history:
        for tc in (m.get("tool_calls") or []):
            id2name[tc["id"]] = tc["function"]["name"]
    # find the last bulky tool-result index (keep that one intact)
    last_bulky = -1
    for i, m in enumerate(history):
        if m.get("role") == "tool" and id2name.get(m.get("tool_call_id")) in _BULKY_TOOLS:
            last_bulky = i
    out = []
    for i, m in enumerate(history):
        if (m.get("role") == "tool" and i != last_bulky
                and id2name.get(m.get("tool_call_id")) in _BULKY_TOOLS):
            out.append({**m, "content": _STUB})
        else:
            out.append(m)
    return out


def run_task(history):
    """Drive the tool loop until the model stops calling tools (task done). ask() may block inside.
    Returns True if a player interruption bubbled up (caller should stop the plan)."""
    for _ in range(MAX_TURNS):
        try:
            throttle_llm()
            t0 = time.monotonic()
            sent = [{"role": "system", "content": SYSTEM}] + compact_for_send(history)
            approx_chars = sum(len(str(m.get("content") or "")) + len(str(m.get("tool_calls") or "")) for m in sent)
            print(f"[llm] calling... msgs={len(sent)} ~{approx_chars}chars")
            resp = client.chat.completions.create(
                model=MODEL,
                messages=sent,
                tools=TOOLS,
            )
            u = getattr(resp, "usage", None)
            tok = f" in={u.prompt_tokens} out={u.completion_tokens}" if u else ""
            print(f"[llm] {time.monotonic() - t0:.1f}s{tok}")
        except Exception as e:
            print(f"[llm error] {e}")
            say("我这边出了点问题,稍后再试。")
            return False

        msg = resp.choices[0].message
        entry = {"role": "assistant", "content": msg.content}
        if msg.tool_calls:
            entry["tool_calls"] = [tc.model_dump() for tc in msg.tool_calls]
        history.append(entry)

        # relay any prose to chat, unless the model already said/asked it via a tool this turn
        spoke_via_tool = msg.tool_calls and any(
            tc.function.name in ("say", "ask") for tc in msg.tool_calls)
        if msg.content and msg.content.strip() and not spoke_via_tool:
            say(msg.content.strip())

        if not msg.tool_calls:
            return False  # task finished (model stopped calling tools)

        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            print(f"[tool] {tc.function.name} {json.dumps(args, ensure_ascii=False)}")
            try:
                out = run_tool(tc.function.name, args)
            except Exception as e:
                out = json.dumps({"error": str(e)})
            print(f"[tool<] {tc.function.name} -> {out[:300]}")
            history.append({"role": "tool", "tool_call_id": tc.id, "content": out})

    say("这个任务步骤太多,我先停下了。需要的话再叫我继续。")
    return False


def main():
    print(f"second_player up — model={MODEL} api={API_URL} mod={MOD}")
    threading.Thread(target=_ws_listener, daemon=True).start()   # game↔agent event channel
    greeted = False
    while True:
        # probe only checks reachability + greets; it must NOT consume the instruction, or the same /tb gets
        # taken here AND left in the WS queue (double-delivery → a phantom interrupt on the first op).
        try:
            mod_get("/state")
        except Exception:
            greeted = False
            time.sleep(3)
            continue
        if not greeted:
            greeted = True
            say("我上线了,用 /tb 指挥我。")

        # single instruction source: next_instruction() merges the WS queue + HTTP fallback, consuming exactly once.
        ins = _pending_instructions.pop(0) if _pending_instructions else next_instruction(block=False)
        if not ins:
            time.sleep(POLL_S)
            continue

        # 甲方案: plan the whole goal once, self-execute, replan only on failure. Brain wakes ~1×/goal.
        run_goal(ins)


if __name__ == "__main__":
    main()
