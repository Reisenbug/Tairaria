from __future__ import annotations

import json
import os
import re

from openai import OpenAI

_SKILL_LIST = """\
explore_right, explore_left, descend,
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
- explore_right/left：向右/左探索，mod自动处理所有跳跃（小坡、障碍、坑）
- descend：下洞穴（按下）
- retreat_right/left：向右/左撤退
- fight_nearest：自动瞄准最近敌人攻击（自动选武器）
- fight_moving_right/left：边移动边攻击
- open_chest：打开最近箱子
- loot_chest：拾取箱子内所有物品
- loot：拾取附近掉落物
- heal：快速使用治疗药水

## 内联控制字段（方式二）

移动：left/right/up/down: true
攻击：use_item: true，mouse_x/mouse_y: 相对玩家中心tile偏移（整数）
交互：quick_heal: true，loot_all: true，interact: true + tile_x/tile_y
切槽：selected_slot: 0-9

注意：不要在控制字段里写 jump:true，跳跃完全由mod自动处理。

## Terraria 游戏规则

- 树木不挡路，玩家可以直接穿过
- terrain_ahead=block_wall 或 pit：继续 explore_right/left，mod自动跳跃处理
- 近战武器(melee)：靠近攻击；远程(ranged)：保持距离；魔法(magic)：需要蓝量
- 血量低于30%系统自动中断并撤退，不需要你处理
- 熔岩(lava)附近立刻用 retreat 反向撤退

## 示例

{{"思考": "地形平坦，向右探索", "skill": "explore_right", "持续秒数": 5.0}}
{{"思考": "前方有墙，mod会自动跳，继续explore", "skill": "explore_right", "持续秒数": 3.0}}
{{"思考": "有敌人，攻击", "skill": "fight_nearest", "持续秒数": 2.0}}
{{"思考": "边走边打", "skill": "fight_moving_right", "持续秒数": 2.0}}
{{"思考": "发现箱子，打开", "skill": "open_chest", "持续秒数": 0.1}}
{{"思考": "需要边走边用特定武器", "控制": {{"right": true, "use_item": true, "mouse_x": 5, "mouse_y": 0}}, "持续秒数": 2.0}}
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class LLMClient:
    def __init__(self) -> None:
        self._client = OpenAI(
            api_key=os.environ.get("COMMANDER_API_KEY", ""),
            base_url=os.environ.get("COMMANDER_API_URL", "https://api.openai.com/v1"),
        )
        self._model = os.environ.get("COMMANDER_MODEL", "gpt-4o")
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
