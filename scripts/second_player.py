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

import fastjudge

load_dotenv()

# print 只到终端,谁也回读不了。同一份也写进文件,和 mod 的 TerraBlindLogs 一样能事后翻。
AGENT_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent.log")


class _Tee:
    def __init__(self, stream, path):
        self.stream = stream
        self.f = open(path, "a", encoding="utf-8", buffering=1)

    def write(self, s):
        self.stream.write(s)
        try:
            self.f.write(s)
        except ValueError:
            pass
        return len(s)

    def flush(self):
        self.stream.flush()
        try:
            self.f.flush()
        except ValueError:
            pass


import sys as _sys
_sys.stdout = _Tee(_sys.stdout, AGENT_LOG)
_sys.stderr = _Tee(_sys.stderr, AGENT_LOG)
print(f"\n===== second_player 启动 {time.strftime('%Y-%m-%d %H:%M:%S')} =====")

MOD = "http://127.0.0.1:17878"
POLL_S = 1.0
NAV_TIMEOUT_S = 240
NAV_REPORT_S = 12       # progress-note cadence while walking
# nav 的 24px 容差是给寻路用的,不是给"到没到"用的。目标在实心块里时它会停在几格外照报 done,
# 调用方信了就去挥镐挥空。2 格 = 挥镐够得着的范围,超了就不算到。
NAV_ARRIVE_CELLS = 2
MAX_TURNS = 60          # tool-loop turns per task (runaway guard)
HISTORY_MAX_MSGS = 80   # rolling conversation memory across tasks

# 超了 RPM 服务器会把多的调用静默排队 ~60s,看着和模型卡死一样 —— 所以自己限速,等的时候大声说
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
        say(f"（配额限流，等 {wait:.0f} 秒再动，别急）", bot=True) if wait >= 5 else None
        time.sleep(wait)
    _last_llm_call = time.monotonic()

# bypass any http_proxy/https_proxy env vars — the mod is on localhost
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def mod_get(path):
    with _opener.open(f"{MOD}{path}", timeout=10) as r:
        return json.loads(r.read().decode())


# 整条下地狱路线要跑两个全图多源 Dijkstra(70万/170万格)再逐段串宝藏,本来就是好几秒的活,
# 不是卡住。10s 一刀切会把正常规划判成 mod 挂了(报 mod unreachable)。
_SLOW = {"/descent_route": 90, "/find_descent": 60}


def mod_post(path, payload):
    req = urllib.request.Request(
        f"{MOD}{path}", data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with _opener.open(req, timeout=_SLOW.get(path, 10)) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"error": f"http_{e.code}"}
    except (urllib.error.URLError, OSError) as e:
        print(f"[mod unreachable] {path}: {e}")
        return {"error": "mod_unreachable"}


def say(text, bot=False):
    """bot=True 是脚本硬编的进度播报(灰蓝),缺省是 LLM 自己写的话(橙)。"""
    print(f"[TB {'bot' if bot else 'says'}] {text}")
    mod_post("/say", {"text": text, "bot": bot})


# ---------------- event channel (game ↔ agent, WebSocket on /ws) ----------------
# mod 推事件过来,不用轮询;ws_send() 反向推(比如打断)也不用走 HTTP
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
        "description": "整张地图可读,所以'这世界有没有钨矿/最近的铁在哪'不是探索问题,是查询问题。给一个 TileID 精确名(不确定先 tile_names 查),返回按距离排序的格坐标。**找矿把 max_dist 开大(2000 以上)**:一次就能知道这世界到底有没有这种矿。扫不到就是真没有(钨和银、铜和锡是二选一生成的,没扫到钨就去扫银),不用查 wiki 猜它在哪一层,也不用自己去找洞口。拿到坐标直接 nav_to,寻路会自己挖竖井下去。找 Containers(箱子)时每个结果带 kind 字段(如 Chest=普通木箱/Gold Chest/Ivy Chest 常春藤箱/Ice Chest 等)。**要特定种类的箱子时,把 n 设大(比如20),从返回列表里筛出 kind 匹配的那个再挑最近**:因为按距离排序时想要的种类可能排在很多其他箱子后面,n 太小会漏掉。找到后 nav_to 到旁边再 interact 开箱。",
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
                                     "description": "沿途收集的 TileID 名,如 Containers/Heart"},
                           "exact": {"type": "boolean",
                                     "description": "目标是矿石/实心块这种人站不上去的格子时传 true。寻路会切到挖矿模式:直接挖竖井过去,落点就在目标那一片里,不会贴到附近地面就说到了。挖矿几乎总该传 true"},
                           "reach": {"type": "boolean",
                                     "description": "开箱子这种够得着就行的,传 true。不用挤到那一格上"}},
            "required": ["x", "y"],
        },
    }},
    {"type": "function", "function": {
        "name": "mine_vein",
        "description": "【要攒够多少个矿就用这个,一次搞定】。给矿种和数量,它自己跑完整个循环:找最近的矿脉 → 挖竖井过去(落在矿脉中间) → 站着把射程内同种矿一次挖光 → 不够就去下一个矿脉,直到数量够或附近没了。**不要自己 find_tiles + nav_to + use_item 一颗颗挖**,那要十几轮还容易数错。返回两个数,别搞混:**tiles_removed=清掉了几格(不代表到手)**,**got=真正进背包的东西(这个才算数)**。两者对不上时会给 warn,通常是寻路挖竖井时把矿顺手清了、掉落物没吸到。停止原因:enough=够了/exhausted=附近没了/tool_weak=镐不够硬/interrupted=玩家打断。挖铁/铅/银/钨/铜/锡/金/铂金这些都走这个。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "矿的 TileID 名,如 Iron/Lead/Silver/Tungsten(不确定先 tile_names 查)"},
                "count": {"type": "integer", "description": "要挖到几个"},
            },
            "required": ["name", "count"],
        },
    }},
    {"type": "function", "function": {
        "name": "mine",
        "description": "【挖穿过去】。从人当前位置朝一个方向一路挖到目标格,自己开竖井/横井,人在哪、该挖哪几格全由它算。**目标够不着、埋在实心块里、要往下挖到深处的矿,一律用这个,别用 use_item**(那个只挥一格,够不着就报 out_of_reach)。也【不用】先 nav_to:寻路站不上去的地方正是该用它的地方。dir 选朝哪个方向挖(down 往下开竖井最常用),target_x/y 给要挖到的那一格。等挖完才返回。返回 outcome:done=挖通了/stalled=挥了半天一格没掉(镐不够硬,换更好的镐)/unbreakable=那格上面压着东西原版不许破坏(换镐没用,先清上面)/out_of_reach=中途够不着了/no_tiles=这个方向没东西可挖/no_pickaxe=背包前十格没镐;mined=实际挖掉几格,got=挖到了什么。",
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
        "description": "对着一个格坐标使用背包里某个槽位的道具,**一步完成**:自动切槽位+瞄准+使用,并等到动作结束才返回。镐挖、斧砍树、剑砍、扔炸弹、用魔杖、喝药都走这个。**放东西不走这个,用 place_at**(它会自己挪脚和补锚点,这里不会)。slot 直接抄 get_state 里那个物品的 slot 字段。x,y 给大概位置即可:砍树/挖矿会自动吸附到最近的树干根部/可挖格,不用你算准。返回 outcome:removed=目标已消失(树倒了/矿挖掉了,成功);no_progress=一下都没啃动,看 reason:reason=tool_weak 是镐/斧不够硬(换更好的);reason=blocked 是上方压着树或箱子(原版不许抽走支撑,先清掉上方那格,换镐没用);**reason=out_of_reach 说明这一格得挖过去而不是站着挥,改用 mine**。挖【挖到为止】,不用你估时间。n/a=喝药/扔炸弹/召唤这种既不采集也不放置的。采集类务必先 find_tiles 拿真实坐标,别自己编。这个工具只挥够得着的一格(砍树、挖脚边的矿);要挖深处或挖穿地形用 mine。",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "目标格x"},
                "y": {"type": "integer", "description": "目标格y"},
                "slot": {"type": "integer", "description": "物品栏槽位号(0-based)"},
                "duration_ticks": {"type": "integer", "description": "【挖和放都不用填】它们挖到/放到为止。只有喝药/扔炸弹/召唤这种没有可观测结果的才需要,默认30"},
            },
            "required": ["x", "y", "slot"],
        },
    }},
    {"type": "function", "function": {
        "name": "place_at",
        "description": "把背包里的东西放到指定格:家具(工作台/熔炉/铁砧/桌椅)、方块、平台、绳子都走这个。**放东西一律用它,别用 use_item**。它自己解决放置的三个条件:够不着就挪脚走过去(行差大了还会先垒柱子/铺平台造落脚点)、身子挡着就让开、挡路的墙挖开、那格四邻没有可附着的锚就从你脚下那块地接一串方块过去。所以地不平、旁边有树、脚下悬空都不用你操心,给个大概位置就行。item 用物品名(中英文都行)。要连放一排就给 n 和 step_x/step_y(比如往右铺5格:n=5,step_x=1)。返回 outcome:done=全放上了/partial=放上一部分就卡住了/stuck=一格都没放上(reason 说卡在哪);cells 逐格说明结果。**一格失败就停,不会闷头刷完**,看 reason 换地方再来。",
        "parameters": {
            "type": "object",
            "properties": {
                "item": {"type": "string", "description": "物品名,如 '工作台' 或 'Wood'"},
                "x": {"type": "integer", "description": "目标格x"},
                "y": {"type": "integer", "description": "目标格y"},
                "n": {"type": "integer", "description": "连放几个,默认1"},
                "step_x": {"type": "integer", "description": "连放时每格往右挪几列(往左给负数),默认0"},
                "step_y": {"type": "integer", "description": "连放时每格往下挪几行(往上给负数),默认0"},
            },
            "required": ["item", "x", "y"],
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
                "name": {"type": "string", "description": "物品名。中文显示名('工作台')或英文内部名('WorkBench'/'Work Bench')都行"},
                "amount": {"type": "integer", "description": "数量,默认1"},
            },
            "required": ["name"],
        },
    }},
    {"type": "function", "function": {
        "name": "track",
        "description": "【要攒够某个数量的东西时,先用这个立台账】。比如查出做铁头盔要15铁锭=45铁矿、还要5铁锭做铁砧,就 track {\"铁矿\":60}。之后**每个动作的返回里都会自动带【进度】字段**(如 铁矿 23/60,够了会标'够了'),数字是从背包实时读的真值。所以挖矿这种要重复十几轮的活,照着进度判断够没够就行,**绝不要自己在脑子里累加**:你看不到被省略的旧结果,一定会数错。攒完一样接着攒下一样时,重新 track 覆盖即可。",
        "parameters": {
            "type": "object",
            "properties": {
                "items": {"type": "object", "description": "物品名->目标数量,如 {\"铁矿\":60,\"石块\":20}"},
            },
            "required": ["items"],
        },
    }},
    {"type": "function", "function": {
        "name": "recipe",
        "description": "查一个物品的配方:要什么材料(每样带 need 要多少 / have 你现在有多少)、要站在哪种工作台旁(stations,空=徒手可做)。没材料的物品也能查——这是查配方,不是查能不能做。要凑齐一批东西时先用它算清楚缺什么,别去猜也别翻wiki。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "物品名。中文('绳')或英文内部名('Rope')都行"},
            },
            "required": ["name"],
        },
    }},
    {"type": "function", "function": {
        "name": "act",
        "description": (
            "最底层的动作原语——按键+光标+使用,你自己编排。上面那些工具做不到的事(搭绳梯、边爬边放、"
            "钩爪、骑坐骑、精确连放)就用这个。\n"
            "steps 数组【串行】执行,一个 step 内的所有字段【同时】生效。\n"
            "坐标一律相对【脚下那一格】(origin):dx>0 向右, dy>0 向下。[0,0]=人所在的格,[0,1]=踩着的地板。"
            "origin 每帧跟着人走,所以 rel 适合边走边做;要钉死在一个世界格上用 at。\n"
            "字段:keys 数组(left/right/up/down/jump/use_tile/throw/hook/mount)、rel或at [dx,dy]=光标位置、"
            "slot=用哪个槽的东西(0-57,抄 get_state)、use=true 持续使用手上的东西、"
            "until=这步什么时候算完(【必填】)、invariant=这步成立的前提,一旦破了立刻停下报告。\n"
            "until 五选一:{\"frames\":N} 按住N帧 / {\"times\":N} 用N次 / "
            "{\"consumed\":{\"item\":物品ID,\"n\":N}} 消耗掉N个 / {\"moved\":{\"dx\":0,\"dy\":-5}} 移动了几格 / "
            "{\"tile\":{\"rel\":[0,-1],\"has\":true}} 某格出现/消失了方块。\n"
            "invariant 三选一:{\"on_rope\":true} 必须挂在绳上 / {\"cursor_in_reach\":true} 光标必须够得到 / "
            "{\"on_ground\":true} 必须站地上。\n"
            "返回 outcome:done=完成;no_progress=进度卡住不动了;invariant_broken=前提破了;timeout=超时。"
            "失败时【会把现场原样给你】——光标在哪一格、够不够得到、那格有没有方块、有没有可附着的邻居、"
            "人在哪/在不在绳上/站没站地、手上拿的什么还剩几个。why 数组列出可疑项。"
            "【看现场自己想明白哪一步错了再改】,别原样重发。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "steps": {"type": "array", "description": "串行执行的步骤", "items": {
                    "type": "object",
                    "properties": {
                        "keys": {"type": "array", "items": {"type": "string"},
                                 "description": "同时按住的键:left/right/up/down/jump/use_tile/throw/hook/mount"},
                        "rel": {"type": "array", "items": {"type": "integer"},
                                "description": "光标格[dx,dy],相对脚下格,每帧跟着人走"},
                        "at": {"type": "array", "items": {"type": "integer"},
                               "description": "光标格[dx,dy],开始时算一次就钉死不动"},
                        "slot": {"type": "integer", "description": "用哪个槽位的物品(0-57)"},
                        "use": {"type": "boolean", "description": "true=持续使用手上的物品"},
                        "until": {"type": "object", "description": "结束条件,必填"},
                        "invariant": {"type": "object", "description": "前提,破了立刻停"},
                    },
                    "required": ["until"],
                }},
                "timeout_frames": {"type": "integer", "description": "总超时帧数,默认1800(30秒)"},
            },
            "required": ["steps"],
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

def _strip_thinking(text):
    """把模型写在正文里的推理剥掉,只留给玩家看的那部分。

    deepseek 这类模型不分 thinking/content,会把"嗯、其实不用问、我直接开口问"整段自言自语
    写进 content,而 run_task 是无条件转发 content 的,于是思考过程全进了游戏聊天。
    有 </think> 就取它之后的;没有就原样返回。"""
    if not text:
        return ""
    for tag in ("</think>", "</thinking>"):
        if tag in text:
            text = text.rsplit(tag, 1)[1]
    return re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", "", text, flags=re.S).strip()


def _slim(state):
    """The minimum a decision needs after an action: where am I, am I hurt.

    【pos 必须是脚下那一格】。/state 的 player.pos 是碰撞箱左上角(p.position),直接 /16 会比
    真实站位高 2~3 格、左 0~1 格,而 act 报的 origin_cell 用的是 mod 的 OriginCx/Cy(覆盖最多
    的列 + 脚底那行)。两套坐标同时喂给模型,它拿这个的坐标去算那个的射程,于是"挖脚下一格"
    都报 out_of_reach。这里照抄 OriginCx/OriginCy 的算法,全局只留一套站位判据。"""
    p = state.get("player", {})
    pos = p.get("pos", {})
    px, py = pos.get("x", 0), pos.get("y", 0)
    w, h = p.get("width", 20), p.get("height", 42)
    c0, c1 = int(px // 16), int((px + w - 1) // 16)
    best, best_cov = c0, -1.0
    for c in range(c0, c1 + 1):
        cov = min(px + w, (c + 1) * 16) - max(px, c * 16)
        if cov > best_cov:
            best, best_cov = c, cov
    return {"pos": {"x": best, "y": int((py + h - 2) // 16)},
            "hp": p.get("hp"), "on_ground": p.get("on_ground")}

def _inv_snapshot():
    return _inv_map(mod_get("/state"))

def _mine_vein(what, count):
    """把 run_find_template 里那套挖矿循环做成 L2 能调的一个动作。

    【为什么不是让模型自己 find+nav+use_item】那要十几轮,而且每轮都得自己判断够没够。
    这里代码自己数,一轮返回。流程和模板那份完全一致,别在这儿另写一套:
      找最近矿脉 -> nav exact(挖竖井过去,落在矿脉里) -> /mine_reach 问射程矩形
      -> 射程内同种矿逐个 use_item strict 挖光 -> 不够就下一个矿脉
    """
    prev_inv = _inv_snapshot()
    # 【removed 不等于到手】。use_item 的 removed 只保证"那格空了",不保证"东西进了包":
    # nav exact 一路挖竖井会把沿途的矿顺手清掉,等这边再去挖,格子早空了,于是 60 次全判成功
    # 而背包一个铁矿没有(现场:mined=60,背包 0,地上掉落物 0,got 里全是石块土块)。
    # 这里不猜物品名(tile 名 Iron 和物品名"铁矿"对不上,硬映射早晚漏),而是两个数都如实报:
    # removed=清掉几格,got=真进包的东西。模型看 got 就知道到底拿到没有,不会被 removed 骗。
    removed, skip, why = 0, set(), "exhausted"
    for _ in range(count + 8):          # 每轮清一个矿脉,留足余量给够不着/挖不动的
        if removed >= count:
            why = "enough"; break
        if next_instruction(block=False):
            why = "interrupted"; break
        r = mod_post("/find_tiles", {"name": what, "n": 30, "max_dist": 2000})
        tiles = [t for t in (r.get("tiles") or []) if (t["x"], t["y"]) not in skip]
        if not tiles:
            break
        tx, ty = tiles[0]["x"], tiles[0]["y"]
        print(f"[vein] locate → ({tx},{ty})  {removed}/{count}")
        nav = json.loads(run_tool("nav_to", {"x": tx, "y": ty, "exact": True, "greed": []}))
        if nav.get("status") == "interrupted":
            why = "interrupted"; break
        if nav.get("status") in ("walled_in", "loop_unresolved", "timeout", "failed"):
            skip.add((tx, ty)); continue
        # 人落在矿脉里了,周围一片都够得着:站着一次挖光,别一颗一颗走过去
        reach = mod_get("/mine_reach")
        if reach.get("error"):
            skip.add((tx, ty)); continue
        mslot = _best_tool_slot("pick")
        rr = mod_post("/find_tiles", {"name": what, "n": 40, "max_dist": 60})
        hit = 0
        for t in (rr.get("tiles") or []):
            if removed >= count:
                break
            ox, oy = t["x"], t["y"]
            if not (reach["lx"] <= ox <= reach["hx"] and reach["ly"] <= oy <= reach["hy"]):
                continue
            res = json.loads(run_tool("use_item", {"x": ox, "y": oy, "strict": True,
                                                   "slot": mslot if mslot is not None else -1,
                                                   "duration_ticks": 0}))
            out, reason = res.get("outcome"), res.get("reason") or ""
            if out == "removed":
                removed += 1; hit += 1
            elif reason == "out_of_reach":
                # 挖脚下会把人挪走(掉进自己挖的洞),这一批的站位就废了。拉黑这格,回外层重新定位
                skip.add((ox, oy)); break
            elif reason == "tool_weak":
                return with_result({"outcome": "tool_weak", "tiles_removed": removed,
                                    "note": f"镐挖不动{what},换更好的镐再来"}, prev_inv)
            else:
                skip.add((ox, oy))
        print(f"[vein] +{hit} → {removed}/{count}")
        if hit == 0:
            skip.add((tx, ty))
    out = {"outcome": why, "tiles_removed": removed, "wanted": count}
    res = json.loads(with_result(out, prev_inv))
    # got 是唯一可信的"到手了多少"。格子清了却什么都没进包,必须当场说破,
    # 不然模型拿着 tiles_removed=60 往下走,到合成那步才发现手里是空的
    if not res.get("got"):
        res["warn"] = (f"清掉了{removed}格,但背包一件东西都没多。多半是寻路挖竖井时把矿顺手清了,"
                       f"掉落物没吸到。去 find_tiles 看看 {what} 还剩多少,或者走回去捡。")
    return json.dumps(res, ensure_ascii=False)


# 【攒东西的台账】。凑 60 个铁矿要十几轮 mine,而每次 with_result 只报这一次的 got,
# 累计数只活在对话历史里,compact_for_send 又会把旧结果 stub 掉。于是模型挖三四轮就
# 觉得差不多了。这里让代码从背包读真值报进度,不靠模型自己数。
_tally = {}      # 物品名 -> 要凑到多少


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
    if _tally:
        # 每个动作都带着台账走,模型不必回头翻历史,也不会把"这一次挖到3个"当成"总共3个"
        base["进度"] = {k: f"{now.get(k, 0)}/{v}" + ("  够了" if now.get(k, 0) >= v else "")
                        for k, v in _tally.items()}
    return json.dumps(base, ensure_ascii=False)


# 顺路采集的额度,单位是【从人当前位置】走过去要多少格 —— 不是离主线多远。
# find_tiles 的 max_dist 是直线距离,隔着山直线 25 格可能要绕几百格,所以判据是 path_cost 问出来的真实路径。
GREED_LIMIT = {"Pots": (3, 10)}      # 最多挖3格、走10格
GREED_WALK_MAX = 40                  # 其他东西:走这么多格以内就顺路拿
GREED_DIG_MAX = 4                    # 顺路可以凿几格;再多就不是顺路了
GREED_DEFAULT = ("Containers", "Heart")   # 不传 greed 时默认盯的东西
SKIP_NEAR_CELLS = 60                 # 下地狱途中:这么近的宝藏不判"在身后",直接去拿


def _worth_detour(cat, tx, ty):
    lim = GREED_LIMIT.get(cat, (GREED_DIG_MAX, GREED_WALK_MAX))
    r = mod_post("/path_cost", {"x": tx, "y": ty})
    if not r.get("ok"):
        # 算不出路就当不值,但要说出来:沉默的 False 和"太远"在日志里长得一模一样
        print(f"[greed] 跳过 {cat}({tx},{ty}):path_cost 算不出路 {r.get('reason') or r}")
        return None   # None=这次算不出,不是"太远" —— 调用方不许拉黑
    dig, walk = r.get("dig", 999), r.get("walk", 999)
    ok = dig <= lim[0] and walk <= lim[1]
    print(f"[greed] {'接受' if ok else '跳过'} {cat}({tx},{ty}):要挖{dig}走{walk},上限{lim[0]}/{lim[1]}")
    return ok


# 处理过就别再回来:掏空的箱子还立在原地,够不着的水晶也还在 —— 地图都分不出来,得自己记
_done_treasures = set()


def _looted(t):
    return (t["x"], t["y"]) in _done_treasures


def _greed_collect(cat, t, nested=False):
    """One side-trip for whitelisted loot while traveling: chest → open+loot, anything else → pick it out.
    Fails FAST — can't reach or can't dent means give up and move on; the journey matters more than any
    single trinket.

    Returns ("interrupted", result) if the player spoke mid-trip (caller hands it up), ("got", None) when the
    treasure is verifiably gone from the map, ("missed", None) otherwise. The caller must not infer success from
    "no interruption": walking off a ledge on the way there ends the trip having collected nothing, and counting
    that as a pickup is how a run reported four treasures it had not necessarily taken."""
    tx, ty = t["x"], t["y"]
    say(f"顺路捡:{t.get('kind') or cat}({tx},{ty})", bot=True)
    # 走过去这一段照旧走 nav_to:它带【顺路采集】(走一段扫一圈,贴着箱子就拐过去),
    # 这是这条路上捡到大部分东西的原因。TreasureGrab 那边只管到了之后的开箱和掏空。
    nav = json.loads(run_tool("nav_to", {"x": tx, "y": ty,
                                         # 箱子够得着就行;矿要挖,得站到位
                                         "reach": cat == "Containers",
                                         "greed": [] if nested else list(GREED_DEFAULT)}))
    if nav.get("status") == "interrupted":
        return "interrupted", nav
    if not nav.get("done") and nav.get("status") != "done":
        print(f"[greed]   放弃 ({tx},{ty}):nav {nav.get('status')} {nav.get('reason','')}")
        return "missed", None
    if cat == "Containers":
        # 【开箱到掏空这一段在 mod 里】。归一锚点、开箱、腾格子、掏空、验收箱子真空了 ——
        # 这边只发一次再轮询。原来这套写在这儿,靠轮询一个不带坐标的全局 last_interact,
        # 读到的 opened 可能是上一个箱子留下的,而"拿到了"只等于"发过 loot_all"。
        st = _hwait("/collect_treasure_status", 600, start=("/collect_treasure", {"x": tx, "y": ty}))
        _done_treasures.add((tx, ty))   # 掏空的箱子不消失,地图证实不了,记下来别再开第二遍
        oc = st.get("outcome")
        if oc in ("done", "partial"):
            if oc == "partial":
                print(f"[greed]   ({tx},{ty}) 只掏了一部分:{st.get('reason')}")
            return "got", None
        print(f"[greed]   ({tx},{ty}) 没拿到:{oc} {st.get('reason','')}")
        return "missed", None
    slot = _best_tool_slot("pick")
    res = json.loads(run_tool("use_item", {"x": tx, "y": ty, "strict": True,
                                           "slot": slot if slot is not None else -1, "duration_ticks": 0}))
    # a mined heart is GONE from the map: ask, don't assume
    cell = mod_post("/probe_cell", {"x": tx, "y": ty})
    if not cell.get("has_tile"):
        return "got", None
    # 够不着/啃不动就别再回来 —— 被怪推开后重新导航,又推开,来回空跑
    if res.get("reason") in ("out_of_reach", "tool_weak", "blocked"):
        print(f"[greed]   拉黑 ({tx},{ty}):{res.get('reason')}")
        _done_treasures.add((tx, ty))
    return "missed", None


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
    if name == "build_replay":
        anchor = None
        if args.get("ax") is not None and args.get("ay") is not None:
            anchor = (int(args["ax"]), int(args["ay"]))
        out = _run_build_replay(anchor)
        return out if isinstance(out, str) else "ok"
    if name == "find_tiles":
        return json.dumps(mod_post("/find_tiles", {
            "name": args["name"], "n": args.get("n", 5), "max_dist": args.get("max_dist", 300)}))
    if name == "nav_to":
        req = {"gx": args["x"], "gy": args["y"]}
        if args.get("exact"):   # mining: goal is a solid ore the body can't stand on — dig a shaft down to it
            req["exact"] = True
        if args.get("reach"):   # 开箱子:够得着就够了,不用挤到箱子那一格
            req["reach"] = True
        # 默认就顺路捡箱子和水晶:七个调用点里六个没传 greed,于是走一路全程不看资源 ——
        # 人贴着木箱走过去都不开。不想要就显式传 greed:[](顺路采集内部就是这么关掉嵌套的)。
        greed = args.get("greed")
        greed = [g for g in greed if isinstance(g, str)] if greed is not None else list(GREED_DEFAULT)
        print(f"[greed] nav_to({args['x']},{args['y']}) 顺路采集={greed or '关'}")
        visited = set()          # loot we already grabbed or gave up on — never circle back
        while True:
            _top_up_platforms()   # 平台是寻路的耗材,每段路开始前补一次
            r = mod_post("/nav_recede", req)
            if not r.get("ok"):
                return json.dumps(r)
            deadline = time.monotonic() + NAV_TIMEOUT_S
            last_report = time.monotonic()
            resume = False
            while time.monotonic() < deadline:
                time.sleep(0.5)
                drain_events()   # 队列无界,没人消费会一直涨
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
                    # 【done 不等于到了】。nav 的容差是给寻路用的(24px),目标在实心岩里、人站
                    # 不上去时它认为"我尽力了"就报 done。调用方信了就去挥镐,于是 out_of_reach
                    # 死循环。"到没到"的判据该按用途定,所以这儿量一次真实距离,差太远就改口。
                    at = d["state"]["pos"]
                    dist = max(abs(at["x"] - args["x"]), abs(at["y"] - args["y"]))
                    if d.get("done") and dist > NAV_ARRIVE_CELLS:
                        d["status"] = "stopped_short"
                        d["done"] = False
                        d["dist"] = dist
                        d["note"] = (f"寻路停在 {dist} 格外(目标多半在实心块里站不上去)。"
                                     f"要挖它就用 mine 直接开过去,别在这儿挥镐。")
                    return json.dumps(d, ensure_ascii=False)
                # 赶路时扫附近的白名单目标,捡完接着走(nav 从人站的地方重启,场是缓存的,恢复不花钱)。
                # 每轮都扫:原来 3 秒一次,人 3 秒跑几十格,捡完一颗转身就走,3 格外的第二颗就甩身后了。
                if greed:
                    hit = None
                    for cat in greed:
                        # 一颗水晶占 4 格、各算一次命中,n 留宽点免得一两颗就占满名额
                        rr = mod_post("/find_tiles", {"name": cat, "n": 24, "max_dist": 25})
                        found = rr.get("tiles") or []
                        # 直线 25 格是硬半径,再近的东西只要超了就根本不在这个列表里 —— 空列表也要记一笔
                        skipped = []
                        for t in found:
                            if (t["x"], t["y"]) in visited or _looted(t):
                                skipped.append(f"({t['x']},{t['y']})已处理")
                                continue
                            worth = _worth_detour(cat, t["x"], t["y"])
                            if not worth:
                                # 只有【确实太远】才永久拉黑。算不出路(None)是暂时的:走几步
                                # 换个位置往往就通了,拉黑等于路过也不开。
                                if worth is False:
                                    visited.add((t["x"], t["y"]))
                                continue
                            hit = (cat, t); break
                        if not hit:
                            print(f"[greed] 扫 {cat}:半径25内 {len(found)} 个,没选中"
                                  + (f" ({','.join(skipped)})" if skipped else ""))
                        if hit:
                            break
                    if hit:
                        cat, t = hit
                        visited.add((t["x"], t["y"]))
                        print(f"[greed] 中途拐去 {cat}({t['x']},{t['y']})")
                        mod_post("/nav_recede_stop", {})
                        # 这一层已经是"半路拐弯"了,再往下不许拐 —— 嵌套到此为止
                        outcome, intr = _greed_collect(cat, t, nested=True)
                        print(f"[greed] {cat}({t['x']},{t['y']}) 结果={outcome}")
                        if outcome == "interrupted":
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
                    say(f"还在走,离目标还有约{int(dist)}格。", bot=True)
            if resume:
                continue
            mod_post("/nav_recede_stop", {})
            return json.dumps({"done": False, "status": "timeout"})
    if name == "mine":
        prev_inv = _inv_snapshot()
        r = mod_post("/mine", {
            "dir": args["dir"], "target_wx": args["target_x"], "target_wy": args["target_y"]})
        if not r.get("ok"):
            return json.dumps(r, ensure_ascii=False)
        # 【等挖完再返回】。原来发完就走,描述里写"用 get_state 看进度",而 SYSTEM 又禁止单独调
        # get_state,两条互相打架,于是模型从来不选这个工具,改用 use_item 一格格怼。
        deadline = time.monotonic() + 180.0
        st = {"outcome": "running"}
        while time.monotonic() < deadline:
            time.sleep(0.2)
            st = mod_get("/mine_status")
            if not st.get("running"):
                break
            if next_instruction(block=False):
                mod_post("/mine_stop", {})
                return json.dumps({"outcome": "interrupted"}, ensure_ascii=False)
        return with_result({"outcome": st.get("outcome"), "reason": st.get("reason"),
                            "mined": st.get("mined")}, prev_inv)
    if name == "use_item":
        prev_inv = _inv_snapshot()
        dur = args.get("duration_ticks", 30)
        r = mod_post("/item_use", {
            "target_wx": args["x"], "target_wy": args["y"],
            "slot": args["slot"], "duration_ticks": dur,
            "strict": bool(args.get("strict"))})
        if not r.get("ok"):
            return json.dumps(r)
        # 采集类挥到地图说"没了"为止,不按次数;这里的超时只防挂死,不是完成判据
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
    if name == "place_at":
        prev_inv = _inv_snapshot()
        n = max(1, int(args.get("n", 1)))
        # 【走 /place_anywhere 不是 /place_at】。后者只是对着那格挥一下,放不上就放不上:
        # 上次放工作台 rejected_no_anchor_hint / occupied(树) 烧掉五轮就是它。
        # 前者会自己挪脚、让位、挖开挡路的、没锚就从脚下接一串过去。
        # 它一次只放一格,要连放就在这儿循环,每格都享受同一套自救。
        sx, sy = int(args.get("step_x", 0)), int(args.get("step_y", 0))
        placed, cells = 0, []
        for k in range(n):
            wx, wy = args["x"] + k * sx, args["y"] + k * sy
            r = mod_post("/place_anywhere", {"item": str(args["item"]), "world": [wx, wy]})
            if not r.get("accepted"):
                cells.append({"at": [wx, wy], "result": r.get("reason", "rejected")})
                break
            deadline = time.monotonic() + 120.0
            st = {"outcome": "running"}
            while time.monotonic() < deadline:
                time.sleep(0.2)
                st = mod_get("/place_anywhere_status")
                if not st.get("running"):
                    break
            out = st.get("outcome")
            cells.append({"at": [wx, wy], "result": out,
                          **({"reason": st.get("reason")} if st.get("reason") else {})})
            if out == "done":
                placed += 1
            else:
                break        # 一格放不上,后面多半同理,别闷头刷完
        return with_result({"outcome": "done" if placed == n else ("partial" if placed else "stuck"),
                            "placed": placed, "wanted": n, "cells": cells}, prev_inv)
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
    # 失败时把现场原样交给 LLM —— 它要靠数字诊断,这里概括或删减就白费了
    if name == "act":
        r = mod_post("/act", {"steps": args["steps"],
                              "timeout_frames": args.get("timeout_frames", 1800)})
        if not r.get("ok"):
            return json.dumps({"outcome": "bad_request", "reason": r.get("reason"),
                               "note": "每个 step 都必须有 until"}, ensure_ascii=False)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            time.sleep(0.2)
            st = mod_get("/act_status")
            if not st.get("active"):
                return json.dumps(st, ensure_ascii=False)
            if next_instruction(block=False):
                mod_post("/act_stop", {})
                return json.dumps({"outcome": "interrupted"}, ensure_ascii=False)
        mod_post("/act_stop", {})
        return json.dumps(mod_get("/act_status"), ensure_ascii=False)
    if name == "loot_all":
        prev_inv = _inv_snapshot()
        r = mod_post("/loot_all", {})
        # 排队的,主线程下一帧才掏。立刻比背包会看到"什么都没拿到"
        time.sleep(0.3)
        return with_result(r, prev_inv)
    if name == "craft":
        prev_inv = _inv_snapshot()
        r = mod_post("/craft", {"item_name": args["name"], "amount": args.get("amount", 1)})
        return with_result(r, prev_inv)
    if name == "recipe":
        return json.dumps(mod_post("/recipe", {"name": args["name"]}), ensure_ascii=False)
    if name == "mine_vein":
        return _mine_vein(args["name"], int(args.get("count", 1)))
    if name == "track":
        items = args.get("items") or {}
        _tally.clear()
        for k, v in items.items():
            try:
                _tally[str(k)] = int(v)
            except (TypeError, ValueError):
                pass
        inv = _inv_map(mod_get("/state"))
        # 【名字对不上要当场喊】。台账的 key 是模型手打的,写成"铁矿石"/"Iron Ore" 就永远 0/60,
        # 而它会一直挖下去等那个永远不涨的数。背包里没有的名字先用 recipe 的 ingredients.name 核对
        # (两边都取游戏本地化名),对不上就说清楚,别静默。
        unseen = [k for k in _tally if k not in inv]
        out = {"tracking": {k: f"{inv.get(k, 0)}/{v}" for k, v in _tally.items()},
               "note": "之后每个动作的返回里都会带【进度】,按它判断够没够,别自己数"}
        if unseen:
            out["warn"] = (f"这些名字现在背包里没有:{unseen}。如果只是还没开始采集那没问题;"
                           f"但要是名字写错了(比如写成内部名或英文名),进度会永远卡在 0。"
                           f"名字以 recipe 返回的 ingredients.name 为准。")
        return json.dumps(out, ensure_ascii=False)
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
- 【攒矿一律 mine_vein】。要多少个就给多少个,它自己找矿脉、挖过去、挖光、不够再找下一个,一次调用搞定。别自己 find_tiles+nav_to+use_item 一颗颗挖。
- 砍树、砸罐子、挖某一个指定的格子:find_tiles 拿坐标(tile 名不确定先 tile_names 查,别猜)再 use_item。看 outcome 判成败,no_progress 按 reason 换法。
- nav_to 去矿石/实心块那种站不上去的格子时传 exact:true,去开箱子传 reach:true。
- 【要攒够数量就先 track】。查清总共要多少(含中间产物和工具的份),track 一次立好台账,
  之后每个动作返回里的【进度】就是真账。别自己累加,也别挖几轮凭感觉说够了。
- 寻路或动作失败,如实告诉玩家原因,提替代方案。
- 玩家能随时打断:工具返回 status=interrupted 时,先回应,再按新意思决定继续/改向/干别的。

知识:你的 Terraria 记忆不可靠。配方先用 recipe 工具查(它直接告诉你要什么材料、还差多少、要哪个工作台);
掉落、数值、召唤条件这类 recipe 查不到的,用 wiki_search + wiki_page 查官方 wiki。
只有"大方向怎么打"这类策略可以自己想。

目标里没说数量、也没说走哪条路时【不许自己定量】:备多少、带什么、走哪边,这些是玩家的账,
不是你的。先 ask 问清楚再动手,问完一次就够,别一步一问。

玩家点名要的东西这世界没有(矿种是二选一生成的,钨/银、铜/锡、铁/铅各只出一种)时,
找到同级替代品【也要先 ask】再做。换目标是玩家的决定,不是你的,哪怕属性完全一样。
"""


# ============================ 甲方案: plan-once + self-execute (LLM-Planner style) ============================
# 脑一次规划完,手自己跑,只有失败才回脑 —— RPM=10 下脑的调用要跟着意外走,不跟着步数走

PLANNER_SYSTEM = """你是 Terraria agent TB 的规划器。给你一个目标 + 当前现状,你一次性输出一条动作序列(JSON),
执行器会自己按序执行,不再回来问你,除非某步失败。所以要一次规划到位。

只输出 JSON:{"say":"给玩家的一句话","plan":[ 动作, 动作, ... ]}

每个动作是一个对象,op 是下面之一:
- {"op":"find","id":"t","what":"<TileID英文名,如Trees/Iron/Containers>","n":1}  在附近找最近的方块,结果存到 id
- {"op":"find_biome","id":"j","what":"jungle"}        全图找生物群系中心(jungle/snow/desert/dungeon/corruption/crimson/hallow)。**去远处的丛林/雪地/地牢用这个,别用 find**
- {"op":"nav","to":"$t.pos"}                          走到某坐标
- {"op":"use","at":"$t.pos","tool":"axe|pick|hammer"}  用工具作用于某格(砍/挖);挖到为止,不用给时间
- {"op":"use","at":[x,y],"slot":N}                  放方块到某格;放到为止,不用给时间。slot 抄现状 items 的 slot 字段,别猜
- {"op":"use","slot":N,"dur":30}                      对自己用的道具(传送杖/喝药/召唤),不带 at;这类才需要 dur
- {"op":"recipe","id":"r","name":"<物品名>"}          查配方:要什么材料、还差多少、要哪个工作台。
  【你的配方记忆不可靠,凡是要合成的东西,先查再排后面的步骤】。差多少由它算,别自己心算。
- {"op":"craft","name":"<物品名,中英文都行>","amount":N}  合成(要站在对应工作台旁)
- {"op":"ask","question":"..."}                       问玩家一句,阻塞等回答。
  【只在信息不足、需要玩家拍板时用,且必须是计划的最后一步】:计划是在答案存在之前排的,
  答案之后的步骤等于闭眼排。所以要问就出一条只有 ask(可带前面的查证步)的短计划,拿到
  回答后你会被重新叫起来,那时再排真正的执行计划。宁可问一句,别替玩家猜。
- {"op":"interact","at":"$c.pos"}                     开箱/开门/机关
- {"op":"loot"}                                       捡光当前箱子
- {"op":"fight","max_dist":25,"seconds":10}           清怪
- {"op":"say","content":"..."}                        中途给玩家说一句(需要边做边解释时)
- {"op":"act","steps":[...],"timeout_frames":1800}    底层动作原语:按键+光标+使用,自己编排。
  【要边做边看的连续动作用它】——搭绳梯、边走边铺平台、钩爪、连放。steps 串行,一个 step 内字段同时生效。
  坐标相对【脚下那一格】:dx>0右, dy>0下, [0,0]=人所在格, [0,1]=踩的地板。rel=每帧跟着人走, at=开始时钉死。
  step 字段:keys(left/right/up/down/jump/use_tile/throw/hook/mount)、rel或at [dx,dy]、slot、use:true、
  until(必填)、invariant(可选,破了立刻停)。
  until 五选一:{"frames":N}/{"times":N}/{"consumed":{"item":物品ID,"n":N}}/{"moved":{"dx":0,"dy":-5}}/
  {"tile":{"rel":[0,-1],"has":true}}。invariant:{"on_rope":true}/{"cursor_in_reach":true}/{"on_ground":true}。
  失败会把现场原样给你(光标在哪/够不够得到/那格有什么/人在不在绳上/手里剩几个),看现场再改,别原样重发。
- {"op":"probe","id":"p","at":"$t.pos"}               查一格:有无背景墙、能否放平台/方块、是否空(結果存id)
- {"op":"measure","id":"m","at":"$t.pos"}             量连通块尺寸:树多高/矿多大/空腔多大(結果存id)

【查完要接着做】。recipe/find/probe 这些只是查,查完什么也没发生。一份只有查询步的计划
不是完整计划 -- 目标说"做一个铅头盔",计划就得一直排到 craft 那一步。

【数量要排满】。plan 是扁平序列,没有"重复N次"这种写法。目标说砍两棵,就老老实实排两轮
find/nav/use(每轮的 find 用不同的 id);说挖十个铁就排十轮,或者用 act 的 repeat。
只排一轮然后指望执行器自己重复,是这里最常见的错。

占位符:find 的结果用 $id.pos 在后续步引用(规划时坐标未知,执行到那步才填)。别自己编坐标。
前置条件自己判断:看现状背包,已有斧就别再规划找斧;缺什么就把补齐步骤也排进 plan。
合成类目标的标准形状:recipe 查清缺什么 → find 缺的矿 → nav → use 挖够 → nav 到工作台 → craft。
现状里会告诉你身边有哪些工作台;要用的那个不在身边,就把「找到它/做一个」也排进去。
tool:"axe"/"pick"/"hammer" 让执行器自动挑背包里最好的那把,你不用管 slot。
tile 名不确定就用常见的(树=Trees,铁矿=Iron,箱子=Containers)。plan 尽量短、直达目标。

你脑内的 Terraria 知识不可靠,只用手上的真实信息:
- 道具用途只信现状里它的 tooltip(括号那句),没写的机制就当没有。
- op 只从上面清单选;物品只用背包里真有的。
- 去远处生物群系用 find_biome 拿位置,别凭记忆报方位。
- 机制/配方不确定就先做能确定的,plan 短一点没关系。

只输出 JSON。"""


# ========== FIND-CLASS TEMPLATE:砍树/挖矿/开箱/打怪同一骨架 locate→nav→act→repeat ==========
# 只让 AI 填变量,骨架由代码跑 —— 它加不了步骤也编不出工具(以前会编"探针"、拿炸弹开路)

FIND_CLASSIFIER_SYSTEM = """把玩家的目标填成一张变量表(JSON),别的不做。这类目标的共同形状是:
「世界上有个东西,找到它→走过去→对它做点什么→重复到够」。只要目标是这个形状,就填表:

{"find_class": true,
 "what": "<找什么:TileID英文名如Trees/Iron/Containers,或biome名如jungle/snow/dungeon>",
 "how": "find" | "find_biome" | "find_descent" | "descend" | "build_replay",
 // find=近处方块; find_biome=去某生物群系(最近边缘);
 // find_descent=去某群系通往地狱的主入口站定(玩家提到主道/主入口/大洞口这类意思);
 // descend=沿主道一路下到地狱,途中按计划捡宝(玩家想去地狱/底层/下矿速降这类意思);biome不明时填jungle
 // build_replay=回放录制好的建造(玩家想照录像盖房子/重现录制的结构这类意思);what/act 留空
 "act": "chop" | "mine" | "open" | "fight" | "none",  // 到了做什么:砍/挖/开箱/打/只是到达
 "count": <砍/挖/开几个目标,默认1>,
 "gather": "<仅当目标是'攒够某物品数量'时填,如 木材>=20;说'砍N棵/挖N个'用 count,别填 gather>",
 "filter": "<可选:筛选,如 Gold Chest>",
 "say": "给玩家的一句话"}

count 和 gather 二选一:数目标个数用 count,攒物品数量用 gather。别两个都填。
如果目标不是这个形状(比如合成装备、造房子、复杂多步),返回 {"find_class": false}。

【关键区分】这张表只管「世界上已经存在、要去找的东西」。
玩家要【用背包里的材料去放置/建造】的,不属于这个形状,一律 {"find_class": false}:
放绳子/搭绳梯/铺平台/垒方块/搭桥/盖墙/放火把/摆家具——这些的材料在背包里,没什么可找的。
反例对照:「挖20个铁」=去世界上找铁矿(填表);「放20个绳子」=用背包的绳子往外放(find_class:false)。
what 只填要去世界上找的目标,永远别把背包里的材料名(Rope/Wood/Platform这类)填进 what。

判定:砍2棵树=what:Trees,act:chop,count:2(不填gather)。挖10铁=what:Iron,act:mine,count:10。
砍树直到木材够20=act:chop,gather:木材>=20(不填count)。去丛林=what:jungle,how:find_biome,act:none。
下地狱/去底层=what:jungle,how:descend,act:none。去丛林主道口=what:jungle,how:find_descent,act:none。
照录像盖房子/回放建造/重现录的结构=how:build_replay(what/act 留空)。
开金箱=what:Containers,act:open,filter:Gold Chest。tile名不确定就用常见的。只输出 JSON。"""


# act → which tool kind to auto-pick。smash(砸罐子)和 chop 同构:对着那格用工具,判 removed。
# 罐子用镐或武器都能砸,这里用镐(开局必有,且不会打空).
_ACT_TOOL = {"chop": "axe", "mine": "pick", "smash": "pick"}


def classify_find(goal):
    """先问快判层是不是 find 形状。不是就直接返回,省掉一整次 LLM 往返(RPM=10 要等 6.5s)。
    是的话才叫 LLM 填变量表 -- 表里 what/count/filter 是要生成的值,那不是判断题。"""
    r = fastjudge.ask("find_shape", {"goal": goal, "note": "材料在背包里的放置/建造不算 find 形状"})
    shape = r["shape"]
    print(f"[fastjudge] shape={shape}")
    if shape.value == "not_find_class" and shape.sure():
        return None
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


def _descent_h(x, y):
    """Cost-to-hell at a cell per the last /descent_route field; -1 = unknown (off-field / no route yet)."""
    try:
        return mod_post("/descent_h", {"x": x, "y": y}).get("h", -1)
    except Exception:
        return -1


# mod 的 kind → 报话里的名字。木箱是 Containers style 0,和金箱/常春藤箱那些分开的
_KN = {"wood_chest": "木箱", "chest": "箱子", "heart": "水晶"}


def _run_descend(bname):
    """ITINERARY descent: walk the chain /descent_route stitched. The mod returns `itinerary` — the treasures
    already ordered into ONE line, each stop priced from the PREVIOUS STOP rather than from the main line. That
    is the fix for the frozen verdict: standing at a treasure 19 tiles off the line, a second one 2 tiles further
    out used to stay written off as "too far", measured against a line the body had already left.

    Python only walks the chain — it does not re-plan it. Progress still defers to the REAL descent field
    (cost-to-hell H): a stop with higher H than the player is behind us — fell past it, got knocked ahead — and
    is skipped rather than climbed back to. The final stretch keeps radius-greed as a net for anything unlisted."""
    _run_descend.arrived = False   # 只有真正走到地狱那一步才置真;中途任何早退都算没到
    r = mod_post("/descent_route", {"name": bname})
    if not r.get("found"):
        say("没找到下地狱的路线。", bot=True)
        return True
    # 路上有什么先数清楚。木箱单独看 —— 少于2个就放宽挖掘额度重查
    def _tally(rr):
        c = {}
        for t in (rr.get("treasures") or []):
            if t.get("tier"):
                c[t["kind"]] = c.get(t["kind"], 0) + 1
        return c

    tal = _tally(r)
    print("[descend] 路上: " + (", ".join(f"{_KN.get(k,k)}×{v}" for k, v in sorted(tal.items())) or "啥也没有"))
    if tal.get("wood_chest", 0) < 2:
        r2 = mod_post("/descent_route", {"name": bname, "dig_max": 30, "dig_max2": 40})
        if r2.get("found"):
            t2 = _tally(r2)
            print(f"[descend] 木箱只有{tal.get('wood_chest',0)}个,放宽到挖30格 → "
                  + ", ".join(f"{_KN.get(k,k)}×{v}" for k, v in sorted(t2.items())))
            if t2.get("wood_chest", 0) > tal.get("wood_chest", 0):
                r, tal = r2, t2
    plan = r.get("itinerary") or []
    plan_kind = {}
    for t in plan:
        plan_kind[t["kind"]] = plan_kind.get(t["kind"], 0) + 1
    say(f"沿主道下地狱,计划途中拿{len(plan)}个宝("
        + "、".join(f"{n}个{_KN.get(k, k)}" for k, n in sorted(plan_kind.items())) + ")。", bot=True)
    # 全程把计划贴出来,不然只能看着人乱跑猜它在干嘛
    for i, t in enumerate(plan):
        print(f"[descend] plan[{i}] {t['kind']} ({t['x']},{t['y']}) line_i={t.get('line_i')}")
    grabbed = missed = skipped = 0
    # 拿到的按种类分开记,不然"收了13个宝"看不出是13个木箱还是13个水晶
    got_kind = {}
    for i, t in enumerate(plan):
        pos = _slim(mod_get("/state"))["pos"]
        ph = _descent_h(pos["x"], pos["y"])
        th = _descent_h(t["x"], t["y"])
        # 每一站都报:现在在哪、下一个目标是什么、离多远。这是唯一能看出"为什么没拿到"的东西
        d = abs(pos["x"] - t["x"]) + abs(pos["y"] - t["y"])
        # 带上人站在哪:只有 H 差看不出它到底在人的哪一边,"擦肩而过还是真在上游"分不了
        note = (f"[{i + 1}/{len(plan)}] 下一个:{t['kind']} ({t['x']},{t['y']}) "
                f"距{d}格 H{th}(我{ph}) 我在({pos['x']},{pos['y']})")
        print(f"[descend] {note}")
        say(note, bot=True)
        # H 比我大 = 离地狱更远 = 在身后。可拐一趟出来人就偏了,近的东西会被误判:
        # (2915,316) 离我 36 格、H 才高 65,那是斜上方不是走过头 —— 近的一律去拿,折回也就几秒。
        if d > SKIP_NEAR_CELLS and ph >= 0 and th >= 0 and th > ph + 30:
            print(f"[descend]   SKIP — H{th} > 我的H{ph}+30 且距{d}格,已经在身后了")
            missed += 1
            skipped += 1
            continue
        # straight to the treasure: the chain already priced the detour, so there is no junction hop first
        # kind 现在有 chest / wood_chest / heart 三种,木箱也是箱子 —— 别把它判成 Heart
        cat = "Heart" if t["kind"] == "heart" else "Containers"
        if _looted(t):
            print(f"[descend]   SKIP — ({t['x']},{t['y']}) 这个我拿过了")
            continue
        # 顺路已经捡掉的东西计划里还留着,轮到它时人跑回去捡空气。水晶挖掉就从地图上消失了,
        # 直接问那一格还在不在最准 —— 掏空的箱子不会消失,那种只能靠 _done_treasures 记着。
        if not mod_post("/probe_cell", {"x": t["x"], "y": t["y"]}).get("has_tile"):
            print(f"[descend]   SKIP — ({t['x']},{t['y']}) 那儿已经空了")
            continue
        outcome, intr = _greed_collect(cat, t)
        if outcome == "interrupted":
            say("(被打断,停下待命)", bot=True); return True
        after = _slim(mod_get("/state"))["pos"]
        if outcome == "got":
            grabbed += 1
            got_kind[t["kind"]] = got_kind.get(t["kind"], 0) + 1
            print(f"[descend]   GOT — 现在在 ({after['x']},{after['y']})")
        else:
            missed += 1
            print(f"[descend]   MISS — 没到,停在 ({after['x']},{after['y']}),离目标还有 "
                  f"{abs(after['x'] - t['x']) + abs(after['y'] - t['y'])} 格")
    nav = json.loads(run_tool("nav_to", {"x": r["hell_x"], "y": r["hell_y"],
                                         "greed": ["Containers", "Heart"]}))
    st = nav.get("status")
    if st == "interrupted":
        say("(被打断,停下待命)", bot=True); return True
    # report the misses too. "收了4个" while silently failing another five is the report a player cannot act on.
    detail = "、".join(f"{n}个{_KN.get(k, k)}" for k, n in sorted(got_kind.items()))
    body = f"收了{grabbed}个宝({detail})" if detail else f"收了{grabbed}个宝"
    # 没拿到的分两种:SKIP=已经在身后了根本没去,MISS=去了没够着。混成一个数看不出该修哪边
    tail = ""
    if missed:
        parts = []
        if skipped: parts.append(f"{skipped}个在身后没去")
        if missed - skipped: parts.append(f"{missed - skipped}个没够着")
        tail = "," + "、".join(parts)
    arrived = bool(nav.get("done") or st == "done")
    if arrived:
        say(f"到地狱了,途中{body}{tail}。", bot=True)
    else:
        say(f"下降中断({st}),已{body}{tail}。", bot=True)
    _run_descend.arrived = arrived      # 到没到,给调用方判断要不要接着开地狱那套
    return True


PLAT_LOW, PLAT_HIGH = 50, 150      # 平台少于50就补到150


def _have(name):
    return _inv_snapshot().get(name, 0)


def _hwait(path, timeout=90, start=None):
    """轮询到 running 变 false。start=(路径, body) 时先发起再等 —— 【必须等它先转起来】,
    否则发完立刻读,mod 那一帧还没 Tick,running 仍是 false,读到的是上一趟的结果。"""
    if start is not None:
        r = mod_post(start[0], start[1])
        if not r.get("ok"):
            return {"outcome": "failed", "reason": r.get("reason", "rejected"), "running": False}
        spin = time.time() + 2
        while time.time() < spin and not mod_get(path).get("running"):
            time.sleep(0.05)
    end = time.time() + timeout
    while time.time() < end:
        st = mod_get(path)
        if not st.get("running"):
            return st
        time.sleep(0.05)
    return mod_get(path)


def _top_up_platforms(reserve=0):
    """平台少于 PLAT_LOW 就补到 PLAT_HIGH。amount 是合成次数,1次吃1木材出2平台。
    平台是寻路的耗材,一路铺一路少,所以每段路之前都要补,不能只在开局搓一次。
    reserve = 要留着不动的木材(盖房前留 125,赶路时不用留)。"""
    have = _have("木平台")
    if have >= PLAT_LOW:
        return have
    times = (PLAT_HIGH - have + 1) // 2
    wood = _have("木材")
    times = min(times, max(0, wood - reserve))
    if times <= 0:
        print(f"[run1] 平台{have},想补但木材只有{wood}(留{reserve})")
        return have
    r = mod_post("/craft", {"item_name": "WoodPlatform", "amount": times})
    now = _have("木平台")
    print(f"[run1] 平台{have}<{PLAT_LOW},合{times}次 → {now}  {r}")
    if r.get("free_slots") == 0:
        say("背包满了,合不了平台。", bot=True)
    return now


def _run_hell(teleport=False):
    """到地狱之后的一整套。编排全在 mod 里(StartHellRun),这边只触发+播报进度。

    别在这儿重推坐标:选址/算线/接力都在 mod 那一份里,python 再算一遍就是第二套判据。

    teleport=True(/tb 2):先把人放到地狱再开跑,只测这一段用。落点也是 mod 算的。
    """
    r = mod_post("/hell_run", {"teleport": True} if teleport else {})
    if not r.get("accepted"):
        say(f"地狱流程起不来:{r.get('reason')}", bot=True)
        return True
    say("到地狱了:选址 → 盖房 → 铺桥 → 召肉山。", bot=True)

    # 整段很长:176 格桥要几分钟,还要等入夜让爆破专家回家。给足时间。
    # 相位变了就播报一次 —— 否则十几分钟一句话没有,看不出死没死
    seen, last = None, time.time()
    end = time.time() + 60 * 60
    while time.time() < end:
        st = mod_get("/hell_run_status")
        if st.get("start_error"):
            say(f"地狱流程起不来:{st['start_error']}", bot=True)
            return True
        ph = st.get("phase", "idle")
        if ph != seen:
            seen, last = ph, time.time()
            print(f"[hell] {ph}")
            say(_HELL_SAY.get(ph.split(":")[0], f"进行中:{ph}"), bot=True)
        if ph == "idle":
            break
        if time.time() - last > 60 * 20:
            say(f"卡在 {ph} 二十分钟了,停手。", bot=True)
            mod_post("/hell_run_stop", {})
            return True
        time.sleep(0.5)

    if st.get("wof_outcome") == "stuck":
        say(f"肉山那套没成:{st.get('wof_reason')}", bot=True)
    return True


_HELL_SAY = {
    "goto": "去桥起点。",
    "anchor": "放第一格。",
    "house": "盖房子。",
    "deck": "铺桥,176 格,要一会儿。",
    "wof": "房子好了,开始召肉山那套(等天黑 → 买雷管 → 换向导)。",
    "fight": "肉山出来了,开打。",
}


def _run_build_replay(anchor=None):
    """TRIGGER ONLY. All record/replay logic lives in the mod (BuildReplayer is a frame-driven state machine:
    nav→place/mine→next, conflict cells skipped, self-contained). Python just kicks it off and relays progress.
    Poll /build_replay_status for a live note; a /tb mid-flight stops the replay and hands control back."""
    req = {"ax": anchor[0], "ay": anchor[1]} if anchor else {}
    r = mod_post("/build_replay_start", req)
    if not r.get("ok"):
        say(f"没法开始回放建造：{r.get('reason', '未知')}", bot=True)
        return True
    say(f"开始回放建造（{r.get('events', '?')} 个事件，冲突 {r.get('conflicts', 0)} 格，淡色已画在屏幕上）。", bot=True)
    last_note = time.monotonic()
    while True:
        time.sleep(0.5)
        interrupt = next_instruction(block=False)
        if interrupt:
            mod_post("/build_replay_stop", {})
            return json.dumps({"done": False, "status": "interrupted", "player_said": interrupt})
        st = mod_get("/build_replay_status")
        if not st.get("running"):
            say(f"建造回放结束：放置{st.get('placed', 0)}，挖掘{st.get('mined', 0)}，"
                f"跳过{st.get('skipped', 0)}{('，' + st['fail_reason']) if st.get('fail_reason') else ''}。", bot=True)
            return True
        if time.monotonic() - last_note >= NAV_REPORT_S:
            last_note = time.monotonic()
            say(f"还在盖：第{st.get('i', 0)}/{st.get('total', 0)}件。", bot=True)


def run_find_template(spec):
    """Run the ONE find-class skeleton from a filled variable table — no AI, no hallucinated ops.
    locate → nav → act → repeat until count/gather met. Returns True if it handled the goal, False to fall back."""
    if spec.get("say"):
        say(spec["say"], bot=True)
    what = spec.get("what")
    how = spec.get("how", "find")
    act = spec.get("act", "none")
    count = int(spec.get("count", 1) or 1)
    filt = (spec.get("filter") or "").strip().lower()
    if how == "build_replay":                        # before biome auto-route: build has no `what`
        return _run_build_replay()
    biome = _biome_of(what)
    if biome:
        what = biome
        if how not in ("find_descent", "descend"):   # descent routing must survive the biome auto-route
            how = "find_biome"
    if how == "descend":
        return _run_descend(biome or "jungle")

    done_count = 0            # targets actually completed (loop-exit counter, NOT a candidate index)
    skip = set()              # coords we couldn't reach → exclude on the next locate
    for _ in range(max(count, 1) + 5):
        # ---- LOCATE ---- always take the NEAREST not-yet-tried target. A completed target has vanished from the
        # world, so the next find naturally surfaces the next one; we only need to exclude the unreachable ones.
        if how == "find_descent":
            r = mod_post("/find_descent", {"name": what})
            if not r.get("found"):
                say(f"没找到{what}的主入口。", bot=True); return True
            tx, ty = r["x"], r["y"]
        elif how == "find_biome":
            r = mod_post("/find_biome", {"name": what})
            if not r.get("found"):
                say(f"没找到{what}。", bot=True); return True
            tx, ty = r["x"], r["y"]
        else:
            r = mod_post("/find_tiles", {"name": what, "n": 20, "max_dist": 400})
            tiles = r.get("tiles") or []
            if filt:
                tiles = [t for t in tiles if filt in str(t.get("kind", "")).lower()] or tiles
            tiles = [t for t in tiles if (t["x"], t["y"]) not in skip]
            if not tiles:
                say(f"附近没有{('可到达的' if skip else '')}{what}了。", bot=True); return True
            tx, ty = tiles[0]["x"], tiles[0]["y"]
        print(f"[tmpl] locate → ({tx},{ty})")

        # ---- NAV ---- 挖矿用 exact:矿在实心岩里人站不上去,nav 直接挖竖井过去,到了矿就没了,不用再挥
        nav = json.loads(run_tool("nav_to", {"x": tx, "y": ty, "exact": act == "mine"}))
        print(f"[tmpl] nav → {nav.get('status')} @ {nav.get('state',{}).get('pos')}")
        if nav.get("status") in ("walled_in", "loop_unresolved", "timeout") or nav.get("status") == "failed":
            skip.add((tx, ty))      # unreachable → exclude it and try the next-nearest
            continue

        # ---- ACT ----  ONE target's completion is the observed world fact: the tile is REMOVED.
        if act == "mine":
            # 人现在站在矿脉里,周围一片都够得着 —— 站着一次挖光,别一颗一颗 nav 过去
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
                        # 挖脚下会把人挪走(掉进自己挖的洞),整批的站位就废了。别对着空气挥,
                        # 交给外层从真实位置重新定位 —— 但这一格要拉黑,不然被击退后又走回来,循环。
                        skip.add((ox, oy))
                        break
                    elif out != "removed":
                        skip.add((ox, oy))
                    # target_gone → already vanished, try the next candidate
                print(f"[tmpl] mine batch → +{mined_here} in reach [{reach['lx']},{reach['ly']}..{reach['hx']},{reach['hy']}]")
            if done_count >= count:
                say(f"搞定,{done_count}个。", bot=True); return True
            continue                              # cluster cleared → locate the next vein
        elif act in ("chop", "smash"):
            # tree: stand beside it, swing the axe until the trunk is REMOVED (or no_progress = can't dent it).
            # smash(罐子)同构:对着那格抡镐,罐子碎了那格就没了 —— 判据同样是 removed,掉落自动进包。
            slot = _best_tool_slot(_ACT_TOOL[act])
            res = json.loads(run_tool("use_item", {"x": tx, "y": ty,
                                                   "slot": slot if slot is not None else -1, "duration_ticks": 0}))
            print(f"[tmpl] act {act} → outcome={res.get('outcome')} snapped={res.get('snapped_to')} got={res.get('got')}")
            if res.get("outcome") == "no_progress":
                say(f"这个砍不动({res.get('reason')})。", bot=True); return True
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
        # ---- DONE? ---- 明确给了数量就以数量为准:"砍2棵"不能因为背包已有木头就不砍
        gather = (spec.get("gather") or "").strip()
        if gather and count <= 1:
            m = re.match(r"(.+?)\s*>=\s*(\d+)", gather)
            if m:
                name, need = m.group(1).strip(), int(m.group(2))
                have = _inv_snapshot().get(name, 0)
                if have >= need:
                    say(f"{name}够了({have})。", bot=True); return True
                continue
        if done_count >= count:
            say(f"搞定,{done_count}个。", bot=True); return True
    say(f"弄完了({done_count}个)。", bot=True)
    return True


def plan_goal(goal, fail_ctx=None):
    """ONE planning call → flat action sequence. fail_ctx (dict) carries replanning context after a failed step.
    Returns (say:str, plan:list) or (None, []) on error."""
    state = slim_world_for_planner()
    user = f"目标:{goal}\n\n现状:\n{state}"
    if fail_ctx:
        user += (f"\n\n上次执行到第{fail_ctx['step']}步 {fail_ctx['op']} 失败:{fail_ctx['result']}\n"
                 f"已完成:{fail_ctx['done']}\n")
        # 【原因要原样给它】。只给"失败"两个字的话,它每轮拿到一样的输入就出一样的计划
        if fail_ctx.get("why"):
            user += f"判据:{fail_ctx['why']}\n"
        user += "给一条修复计划接着干(别从头)。"
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
        # 功能性道具附上原版 tooltip:脑记不住"和谐杖"是干嘛的,会自己编("需要魔力")
        cat = it.get("category", "misc")
        if tip_budget > 0 and cat in ("misc", "consumable"):
            info = mod_post("/item_info", {"slot": it.get("slot")})
            tip = (info.get("tooltip") or "").strip()
            if tip:
                line += f"（{tip[:80]}）"
                tip_budget -= 1
        items.append(line)
    w = st.get("world", {})
    # 合成要站在工作台旁,而规划器看不见世界。不报的话它只能假设台子就在脚边,craft 到了才失败
    return (f"位置格({round(pos.get('x',0)/16)},{round(pos.get('y',0)/16)}) hp{p.get('hp')} biome={p.get('biome')} "
            f"{'夜' if not w.get('day') else '昼'}{' 血月' if w.get('blood_moon') else ''}\n"
            f"背包:{', '.join(items)}\n"
            f"身边工作台:{_nearby_stations()}")


_STATION_TILES = {"WorkBenches": "工作台", "Furnaces": "熔炉", "Anvils": "铁砧",
                  "Tables": "桌子", "Chairs": "椅子", "Hellforge": "地狱熔炉"}


def _nearby_stations():
    """够得着的工作台,给规划器判断 craft 前要不要先走过去/先做一个。"""
    found = []
    for name, zh in _STATION_TILES.items():
        try:
            r = mod_post("/find_tiles", {"name": name, "n": 1, "max_dist": 40})
            t = (r.get("tiles") or [None])[0]
            if t:
                found.append(f"{zh}({t['x']},{t['y']})")
        except Exception:
            pass
    return ", ".join(found) or "无"


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
    # 规划器总对生物群系用 find(本地扫描看不见远处,返回空计划就死),代码兜底改判,别指望提示词
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
    if o == "act":
        return run_tool("act", {"steps": op["steps"],
                                "timeout_frames": op.get("timeout_frames", 1800)})
    if o == "recipe":
        out = run_tool("recipe", {"name": op["name"]})
        if op.get("id"):
            results[op["id"]] = json.loads(out)
        return out
    if o == "ask":
        # 阻塞等玩家回话。答案存进 results 供后续步引用,但真正的用法是【问完这一轮就结束】:
        # 计划是在答案存在之前生成的,答案之后的步骤等于闭着眼睛排的。见 PLANNER_SYSTEM 里的 ask 约定。
        out = run_tool("ask", {"question": op["question"]})
        if op.get("id"):
            results[op["id"]] = json.loads(out)
        return out
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


# an op result is a FAILURE (→ wake the brain) if it carries these signals. removed/placed/done/cleared/crafted = success.
_FAIL_SIGNALS = ("error", "no_progress", "not_placed", "no_swing", "walled_in", "loop_unresolved", "timeout", "unresolved_coord")

def failure_kind(op, result_str):
    """失败之后该重试还是该重规划。分不清就会把可重试的当死局叫醒 LLM(等 6.5s),
    或者把死局反复重试到超时"""
    r = fastjudge.ask("op_failure", {"operation": op, "result": result_str[:600]})
    kind = r["kind"]
    print(f"[fastjudge] failure={kind}")
    return kind.value if kind.sure() else None


def op_failed(result_str):
    try:
        d = json.loads(result_str)
    except Exception:
        return False
    # not_placed/no_swing = placement produced no tile (the eye that used to be blind); reason says why.
    # invariant_broken/bad_request come from /act — a step's premise snapped, or the chain was malformed.
    if d.get("outcome") in ("no_progress", "timeout", "not_placed", "no_swing",
                            "invariant_broken", "bad_request"):
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
    """Top loop. FAST PATH: if the goal is a find-class task (chop/mine/goto/open/fight/descend), the AI fills a
    variable table and code runs the fixed skeleton — no hallucinated ops. FALLBACK: 甲方案 free planning for
    everything else. Understanding intent is the BRAIN's job; code only guarantees execution after routing."""
    drain_stale_instructions()
    _tally.clear()      # 台账跟着目标走,上个目标的指标不能漏到下一个

    # 2 = 只测地狱那一段:直接把人放到地狱再跑,跳过砍树/盖房/下降。
    # 传送目标由 mod 算(HellLanding),这边照旧只是触发
    if goal.strip() == "2":
        say("跳过前面,直接测地狱那一段。", bot=True)
        # 跳过了备料那几步,但地狱那套照样要平台(寻路耗材)和方块(176 格桥)。
        # 木头有 mod 那边的让步自动补,平台得自己搓
        _top_up_platforms()
        _run_hell(teleport=True)
        return

    # 【模板优先】。砍树/挖矿/开箱这类 find 形状,模板早就跑通了(失败换下一个目标而不是惊动大模型);
    # 激进层排在它后面,专攻模板覆盖不了的:合成、建造、多步
    ai_mode = goal.strip().startswith("ai ")
    if ai_mode:
        goal = goal.strip()[3:].strip()

    spec = classify_find(goal)
    if spec:
        print(f"[find-template] {spec}")
        run_find_template(spec)
        return

    if ai_mode:
        import agent_loop
        if agent_loop.run(goal, _sys.modules[__name__]):
            return

    # 剩下的交给工具循环:一步一看,上一步的返回值决定下一步。
    # 【为什么不是一次性规划】查配方才知道缺多少、问了玩家才知道备多少:这类目标的后一步依赖
    # 前一步的返回值,而一次性计划是在那些值存在之前就排完的,只能靠失败重排去试错。
    # plan_goal / PLANNER_SYSTEM 暂时留着:RPM 扛不住的话还要退回去分流。
    history = [{"role": "user", "content": f"目标:{goal}\n\n现状:\n{slim_world_for_planner()}"}]
    run_task(history)


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
            say("我这边出了点问题,稍后再试。", bot=True)
            return False

        msg = resp.choices[0].message
        entry = {"role": "assistant", "content": msg.content}
        if msg.tool_calls:
            entry["tool_calls"] = [tc.model_dump() for tc in msg.tool_calls]
        history.append(entry)

        # relay any prose to chat, unless the model already said/asked it via a tool this turn
        spoke_via_tool = msg.tool_calls and any(
            tc.function.name in ("say", "ask") for tc in msg.tool_calls)
        if msg.content and not spoke_via_tool:
            spoken = _strip_thinking(msg.content)
            if spoken:
                say(spoken)

        if not msg.tool_calls:
            return False  # task finished (model stopped calling tools)

        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            print(f"[tool] {tc.function.name} {json.dumps(args, ensure_ascii=False)}")
            try:
                out = run_tool(tc.function.name, args)
            except Exception as e:
                out = json.dumps({"error": str(e)})
            # 失败了先问 Jev 是哪一种。可重试的当场重来,不必为它唤醒 LLM(等 6.5s)。
            # 【一个 tool_call_id 只能回一条】,所以重试的结果要并进同一条里
            if op_failed(out) and failure_kind(tc.function.name, out) == "retry_same":
                try:
                    out2 = run_tool(tc.function.name, args)
                except Exception as e:
                    out2 = json.dumps({"error": str(e)})
                print(f"[tool<retry] {tc.function.name} -> {out2[:300]}")
                out = json.dumps({"first_attempt_failed": json.loads(out) if out.startswith("{") else out,
                                  "retried": json.loads(out2) if out2.startswith("{") else out2},
                                 ensure_ascii=False)
            print(f"[tool<] {tc.function.name} -> {out[:300]}")
            history.append({"role": "tool", "tool_call_id": tc.id, "content": out})

    say("这个任务步骤太多,我先停下了。需要的话再叫我继续。", bot=True)
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
            say("我上线了,用 /tb 指挥我。", bot=True)

        # single instruction source: next_instruction() merges the WS queue + HTTP fallback, consuming exactly once.
        ins = _pending_instructions.pop(0) if _pending_instructions else next_instruction(block=False)
        if not ins:
            time.sleep(POLL_S)
            continue

        # 甲方案: plan the whole goal once, self-execute, replan only on failure. Brain wakes ~1×/goal.
        run_goal(ins)


def release_game():
    """Ctrl+C must NOT leave the character possessed: stop every coordinator that could still be driving
    controls (nav walking, pick swinging, mining, placing, fighting). Best-effort — the mod may be gone."""
    for path in ("/nav_recede_stop", "/item_use_stop", "/mine_stop", "/place_stop",
                 "/walk_to_edge_stop", "/jump_stop"):
        try:
            mod_post(path, {})
        except Exception:
            pass
    try:
        say("我下线了。", bot=True)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[exit] releasing game controls...")
        release_game()
