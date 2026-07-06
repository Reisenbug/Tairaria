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

API_URL = os.environ.get("SECOND_PLAYER_API_URL") or os.environ.get("COMMANDER_API_URL", "https://api.openai.com/v1")
API_KEY = os.environ.get("SECOND_PLAYER_API_KEY") or os.environ.get("COMMANDER_API_KEY", "")
MODEL = os.environ.get("SECOND_PLAYER_MODEL") or os.environ.get("COMMANDER_MODEL", "")

client = OpenAI(base_url=API_URL, api_key=API_KEY, timeout=120, max_retries=1)

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
        "description": "用 Bellman 寻路走/跳/挖/搭桥到目标格坐标。阻塞直到到达、失败或超时,返回结果。失败带原因码(walled_in/loop_unresolved/timeout等)——如实告诉玩家并考虑替代方案。",
        "parameters": {
            "type": "object",
            "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
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
        "description": "对着一个格坐标使用背包里某个槽位的道具——**一步完成**:自动切到那个槽位+瞄准该格+使用。镐子挖、剑砍、放置方块、扔炸弹、用魔杖、喝药水都走这个。不需要先'切槽位'再'用',这一个调用就干完了。slot=物品的槽位号(直接抄 get_state 的 items 里那个物品的 slot 字段)。扔炸弹到脚下就是 x,y=脚下格、slot=炸弹的slot。道具有射程,先站近。",
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
    if name == "tile_names":
        return json.dumps(mod_post("/tile_names", {"q": args.get("q", "")}))
    if name == "find_tiles":
        return json.dumps(mod_post("/find_tiles", {
            "name": args["name"], "n": args.get("n", 5), "max_dist": args.get("max_dist", 300)}))
    if name == "nav_to":
        r = mod_post("/nav_recede", {"gx": args["x"], "gy": args["y"]})
        if not r.get("ok"):
            return json.dumps(r)
        deadline = time.monotonic() + NAV_TIMEOUT_S
        last_report = time.monotonic()
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
                return json.dumps(d)
            # periodic progress note so the player isn't staring at a black screen
            if time.monotonic() - last_report >= NAV_REPORT_S:
                last_report = time.monotonic()
                st = mod_get("/state")
                pos = st.get("player", {}).get("pos", {})
                px, py = pos.get("x", 0) / 16, pos.get("y", 0) / 16
                dist = abs(px - args["x"]) + abs(py - args["y"])
                say(f"还在走,离目标还有约{int(dist)}格。")
        mod_post("/nav_recede_stop", {})
        return json.dumps({"done": False, "status": "timeout"})
    if name == "mine":
        return json.dumps(mod_post("/mine", {
            "dir": args["dir"], "target_wx": args["target_x"], "target_wy": args["target_y"]}))
    if name == "use_item":
        return json.dumps(mod_post("/item_use", {
            "target_wx": args["x"], "target_wy": args["y"],
            "slot": args["slot"], "duration_ticks": args.get("duration_ticks", 30)}))
    if name == "interact":
        return json.dumps(mod_post("/interact", {"tile_x": args["x"], "tile_y": args["y"]}))
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
        return json.dumps(mod_post("/loot_all", {}))
    if name == "craft":
        return json.dumps(mod_post("/craft", {"item_name": args["name"], "amount": args.get("amount", 1)}))
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

行为:
- 说中文,简短,像队友。你的动作玩家看不见,用 say 边干边说:开始/关键进展/完成/失败各说一句。
- 拿不准就用 ask 问玩家(目标模糊、要拍板),拿到答案继续。同名或陌生物品先 item_info 查清楚再决定。
- 想清楚就动手,别空转。use_item 一步完成切槽+瞄准+使用。
- 寻路或动作失败,如实告诉玩家原因,提替代方案。
- 玩家能随时打断:工具返回 status=interrupted 时,先回应玩家的话,再按新意思决定继续/改向/干别的。

知识:你的 Terraria 记忆不可靠。配方、掉落、数值、召唤条件一律 wiki_search + wiki_page 查官方 wiki。
只有"大方向怎么打"这类策略可以自己想。
"""


PLANNER_SYSTEM = """你是 Terraria agent TB 的规划器。玩家给一个目标,你判断它是简单的一步任务,
还是需要拆成多个子任务的复合目标,然后只输出 JSON(不要别的话)。

规则:
- 简单直接的目标(如"去丛林""开最近的木箱""挖10个铁")→ {"multi": false}
- 开放/复合目标(如"去丛林发育一下""准备打史莱姆王""搞一套铁装")→ 拆成有序、可执行、
  各自有明确完成标准的子任务列表:{"multi": true, "subtasks": ["子任务1", "子任务2", ...]}
- 子任务要具体可执行(一个子任务对应一段明确的行动),别写"发育"这种模糊的。
- 每个子任务是给 TB 的一句中文指令。3~6 个为宜,别拆太碎。
- 不确定的游戏知识别在这里瞎编数值,拆任务时说清目标即可(具体数值执行时 TB 会查 wiki)。

只输出 JSON。"""


def plan_goal(goal):
    """One planning call: decide single vs multi-step. Returns (multi:bool, subtasks:list)."""
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": PLANNER_SYSTEM},
                      {"role": "user", "content": goal}],
            response_format={"type": "json_object"},
        )
        d = json.loads(resp.choices[0].message.content)
        if d.get("multi") and isinstance(d.get("subtasks"), list) and d["subtasks"]:
            return True, [str(s) for s in d["subtasks"]]
    except Exception as e:
        print(f"[planner error] {e}")
    return False, []


def run_plan(goal, subtasks):
    """Execute a multi-step plan: each subtask gets a fresh, compact context (goal + progress +
    current subtask), so history never balloons. Player can interrupt between/within subtasks."""
    say(f"这个目标我拆成{len(subtasks)}步:" + "、".join(subtasks) + "。开始。")
    done = []
    for i, sub in enumerate(subtasks):
        progress = ";".join(f"{j+1}.{d}✓" for j, d in enumerate(done)) or "(还没开始)"
        header = (f"【总目标】{goal}\n【已完成】{progress}\n"
                  f"【当前子任务 {i+1}/{len(subtasks)}】{sub}\n"
                  f"专心完成这一个子任务。做完就停(不用宣布整个计划完成)。")
        say(f"[{i+1}/{len(subtasks)}] {sub}")
        history = [{"role": "user", "content": header}]
        interrupted = run_task(history)
        if interrupted:   # player cut in mid-subtask → abort the plan, let them redirect
            say("计划先停在这儿,你说。")
            return
        done.append(sub)
    say("整个目标都办完了。")


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
            t0 = time.monotonic()
            print("[llm] calling...")
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": SYSTEM}] + compact_for_send(history),
                tools=TOOLS,
            )
            print(f"[llm] {time.monotonic() - t0:.1f}s")
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
    history = []
    greeted = False
    while True:
        # wait for the mod to be reachable, greet once per connection
        try:
            probe = mod_get("/instruction")
        except Exception:
            greeted = False
            time.sleep(3)
            continue
        if not greeted:
            greeted = True
            say("我上线了,用 /tb 指挥我。")

        ins = probe.get("instruction") or next_instruction(block=False)
        if not ins:
            time.sleep(POLL_S)
            continue

        # PLAN vs ACT: an open/compound goal gets decomposed into subtasks, each run in its own
        # compact context. A simple goal runs conversationally with rolling memory.
        multi, subtasks = plan_goal(ins)
        if multi:
            print(f"[plan] {len(subtasks)} subtasks: {subtasks}")
            run_plan(ins, subtasks)
        else:
            history.append({"role": "user", "content": ins})
            run_task(history)
            if len(history) > HISTORY_MAX_MSGS:
                del history[:len(history) - HISTORY_MAX_MSGS]
                while history and history[0].get("role") != "user":
                    del history[0]


if __name__ == "__main__":
    main()
