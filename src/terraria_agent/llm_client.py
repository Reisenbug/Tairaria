from __future__ import annotations

import json
import os
import re

from openai import OpenAI

_SKILL_LIST = """\
explore_right, explore_left, jump_right, jump_left, descend,
retreat_right, retreat_left, loot, heal,
fight_nearest, fight_moving_right, fight_moving_left,
open_chest, loot_chest\
"""

_SYSTEM = f"""\
你是一个控制 Terraria 玩家的 Commander AI。你的目标是探索世界、生存、收集资源。

每次收到当前游戏状态后，输出一条指令。执行层持续执行该指令直到下次触发。

## 输出格式（二选一）

方式一：使用预定义技能（推荐）
{{"思考": "...", "skill": "<技能名>", "持续秒数": N}}

方式二：内联控制（技能库不够用时）
{{"思考": "...", "控制": {{...}}, "持续秒数": N}}

## 可用技能

{_SKILL_LIST}

技能说明：
- explore_right/left：向右/左探索（mod自动处理跳跃避坑）
- jump_right/left：跳跃越过障碍
- descend：下洞穴
- retreat_right/left：跳跃撤退
- fight_nearest：自动瞄准最近敌人攻击（自动选武器）
- fight_moving_right/left：边移动边攻击
- open_chest：打开最近箱子
- loot_chest：拾取箱子内所有物品
- loot：拾取附近掉落物
- heal：快速使用治疗药水

## 内联控制字段（方式二）

移动：left/right/up/down: true，jump: true
攻击：use_item: true，mouse_x/mouse_y: 相对玩家中心tile偏移（整数）
交互：quick_heal: true，loot_all: true，interact: true + tile_x/tile_y
切槽：selected_slot: 0-9

## Terraria 游戏规则

- 树木不挡路，玩家可以直接穿过，不需要砍
- 实心方块才是真正障碍，需要跳跃或挖开
- terrain_ahead=block_wall：前方有墙，用jump_right越过
- terrain_ahead=pit：前方有坑，mod自动处理，继续explore即可
- 近战武器(melee)：靠近攻击；远程(ranged)：保持距离；魔法(magic)：需要蓝量
- 血量低于30%系统自动中断并撤退，不需要你处理
- 熔岩(lava)附近立刻向上或反向撤退

## 示例

{{"思考": "地形平坦，向右探索", "skill": "explore_right", "持续秒数": 5.0}}
{{"思考": "前方有墙，跳跃越过", "skill": "jump_right", "持续秒数": 0.5}}
{{"思考": "有敌人，攻击", "skill": "fight_nearest", "持续秒数": 2.0}}
{{"思考": "边走边打", "skill": "fight_moving_right", "持续秒数": 2.0}}
{{"思考": "发现箱子，打开", "skill": "open_chest", "持续秒数": 0.1}}
{{"思考": "需要同时跳跃攻击，技能库没有", "控制": {{"right": true, "jump": true, "use_item": true, "mouse_x": 3, "mouse_y": -2}}, "持续秒数": 1.0}}
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class LLMClient:
    def __init__(self) -> None:
        self._client = OpenAI(
            api_key=os.environ.get("TACTICIAN_API_KEY", ""),
            base_url=os.environ.get("TACTICIAN_API_URL", "https://api.openai.com/v1"),
        )
        self._model = os.environ.get("TACTICIAN_MODEL", "gpt-4o")
        self._history: list[dict] = []

    def decide(self, state_text: str) -> dict:
        self._history.append({"role": "user", "content": state_text})
        if len(self._history) > 20:
            self._history = self._history[-20:]

        print("[llm] 调用 API...")
        msg = self._client.chat.completions.create(
            model=self._model,
            max_tokens=256,
            timeout=30,
            messages=[{"role": "system", "content": _SYSTEM}] + self._history,
        )
        raw = msg.choices[0].message.content.strip()
        print(f"[llm] 原始输出={raw!r}")
        self._history.append({"role": "assistant", "content": raw})

        m = _JSON_RE.search(raw)
        if not m:
            return {}
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            return {}
