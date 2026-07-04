"""TerraBlind second-player agent.

An LLM agent that plays Terraria alongside the human. The player types /tb <text> in game chat;
the agent runs a tool-calling loop driving the mod's HTTP primitives (state/find/nav/mine/...),
talks back through in-game chat, and — crucially — can ask the player a question mid-task and
BLOCK on their reply (the next /tb), then continue the SAME task. Not one-shot per /tb.

Run:    python scripts/second_player.py      (game running with the TerraBlind mod loaded)
Config: SECOND_PLAYER_API_URL / SECOND_PLAYER_MODEL / SECOND_PLAYER_API_KEY in .env,
        falling back to COMMANDER_* (same convention as llm_client.py).
"""

import json
import os
import time
import urllib.error
import urllib.request

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

MOD = "http://127.0.0.1:17878"
POLL_S = 1.0
NAV_TIMEOUT_S = 240
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


def next_instruction(block=False):
    """Return the next queued /tb text, or None. If block=True, wait until one arrives."""
    while True:
        try:
            ins = mod_get("/instruction").get("instruction")
        except Exception:
            ins = None
        if ins:
            print(f"[instruction] {ins}")
            return ins
        if not block:
            return None
        time.sleep(POLL_S)


# ---------------- tools ----------------

TOOLS = [
    {"type": "function", "function": {
        "name": "get_state",
        "description": "获取当前游戏状态快照:玩家血量/魔力/位置(像素,除以16得到格坐标)/速度/biome/背包装备。用它确认自己在哪、身上有什么。",
        "parameters": {"type": "object", "properties": {}},
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
        "description": "在玩家周围找最近的某类方块,按距离排序返回格坐标。name 用原版 TileID 精确名,如 Iron/Copper/Gold/Silver/Demonite/Containers(箱子)/Trees/Hellstone。找 Containers 时每个结果会带 kind 字段(箱子种类名,如 Chest=木箱/Gold Chest/Ice Chest…);要'最近的木箱'就找 Containers 再挑 kind 是木箱(Chest)的最近一个。找到箱子后 nav_to 到旁边再 interact 开箱。",
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
        "description": "对着一个格坐标使用背包里某个槽位的道具(镐子挖、剑砍、放置物、药水、魔杖等都走这个)。slot 是物品栏槽位号(0-based,见 get_state 的 inventory)。先确认自己站得离目标够近(道具有射程)。",
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
        return json.dumps(mod_get("/state"))
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
        while time.monotonic() < deadline:
            time.sleep(0.5)
            d = mod_get("/nav_recede_done")
            if d.get("done") or d.get("status") == "failed":
                return json.dumps(d)
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
    if name == "ask":
        say(args["question"])
        answer = next_instruction(block=True)   # BLOCK the task until the player replies with /tb
        return json.dumps({"player_answer": answer})
    if name == "say":
        say(args["text"])
        return "ok"
    return json.dumps({"error": f"unknown tool {name}"})


# ---------------- agent loop ----------------

SYSTEM = """你是 TB,Terraria 世界里的 AI 二号玩家,和人类玩家搭档。你是一个 agent:接到目标后自己
分解、执行、遇到疑问就问玩家、拿到答案继续,直到把事办成。不是一问一答的机器人。

你看不到画面。你的感官和手就是工具。玩家在聊天里给你目标,你执行并回话。

核心规则:
- 说中文,简短,像队友。玩家看不到你的任何动作,不说就等于没发生。
- **边干边说**:调用寻路/挖掘这类耗时工具前先说一句要干嘛,拿到关键结果再说一句。装高手一言不发是大忌。
- **有疑问直接用 ask 问玩家,然后继续**。ask 会阻塞等玩家回答,回答回来你接着干,任务不断。
  该问就问(目标模糊、要玩家拍板),别瞎猜;但也别为了省事把简单决定丢给玩家。
- get_state 位置是像素,除以16是格坐标;所有工具坐标都用格坐标。
- 寻路失败(walled_in/loop_unresolved/timeout)要用人话告诉玩家原因并提替代方案。绝不假装成功。

找地形(比如"去丛林"):整张地图可读,别盲走探索。用 find_biome(name) 拿到丛林中心坐标,
再 nav_to 过去。支持 jungle/snow/desert/dungeon/corruption/crimson/hallow。

找方块:先用 tile_names(关键词) 查准确的 TileID 名,再用 find_tiles(那个名) 找位置——别猜名字。
地下的东西(生命水晶等)半径要给大(max_dist 800+),够不到就加大或先往地下走一段再找。

你精通 Terraria(配方、矿物深度、进度门槛、地理)。按步骤干:查状态 → 定位目标 → 寻路 → 行动 → 验证。
"""


def run_task(history):
    """Drive the tool loop until the model stops calling tools (task done). ask() may block inside."""
    for _ in range(MAX_TURNS):
        try:
            t0 = time.monotonic()
            print("[llm] calling...")
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": SYSTEM}] + history,
                tools=TOOLS,
            )
            print(f"[llm] {time.monotonic() - t0:.1f}s")
        except Exception as e:
            print(f"[llm error] {e}")
            say("我这边出了点问题,稍后再试。")
            return

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
            return  # task finished

        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            print(f"[tool] {tc.function.name} {json.dumps(args, ensure_ascii=False)}")
            try:
                out = run_tool(tc.function.name, args)
            except Exception as e:
                out = json.dumps({"error": str(e)})
            history.append({"role": "tool", "tool_call_id": tc.id, "content": out})

    say("这个任务步骤太多,我先停下了。需要的话再叫我继续。")


def main():
    print(f"second_player up — model={MODEL} api={API_URL} mod={MOD}")
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

        history.append({"role": "user", "content": ins})
        run_task(history)

        if len(history) > HISTORY_MAX_MSGS:
            del history[:len(history) - HISTORY_MAX_MSGS]
            while history and history[0].get("role") != "user":
                del history[0]


if __name__ == "__main__":
    main()
