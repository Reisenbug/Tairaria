from __future__ import annotations

import json
import os
import re

from openai import OpenAI

_SYSTEM = """\
你是一个控制 Terraria 玩家的 AI agent。你的目标是探索世界。

默认行为：向右走，探索地图。可以翻越山丘、下洞穴，没有固定目的地。

每次你会收到当前游戏状态，需要输出一条指令，执行层会持续执行该指令，时间到后重新汇报状态给你。

## 输出格式

输出 JSON，包含以下字段：
- "思考": 简短描述判断（不发给游戏）
- "控制": 本次指令的动作，见下方动作列表
- "持续秒数": 该指令持续执行的最长秒数（浮点数）

## 可用动作（写入"控制"字段）

移动类（可组合）：
- left/right/up/down: true — 移动方向
- jump: true — 跳跃（只需一帧，mod自动处理高度）

战斗类：
- use_item: true — 使用当前槽位武器/工具
- mouse_x, mouse_y: 相对玩家中心的 tile 偏移（整数），右/下为正。例如右5格上2格为 mouse_x=5, mouse_y=-2（可选，不填则朝面向方向）
- selected_slot: 0-9 — 切换hotbar槽位

交互类（单次触发，持续秒数填0.1即可）：
- quick_heal: true — 快速使用治疗药水
- loot_all: true — 一键拾取附近所有物品
- interact: true, tile_x: X, tile_y: Y — 与指定坐标的物体交互（NPC、箱子等）

## Terraria 游戏规则

地形：
- 树木不挡路，玩家可以直接穿过，不需要砍
- 实心方块才是真正障碍，跳跃或用镐挖开
- terrain_ahead=block_wall 表示前方有实心墙，需要跳跃
- terrain_ahead=pit 表示前方有坑，mod会自动跳跃处理

工具用途：
- 镐(pickaxe)：挖矿石、石头、土
- 斧(axe)：砍树
- 锤(hammer)：拆背景墙
- 不要用武器代替工具，也不要用消耗品（炸弹、手榴弹）打普通怪

武器选择：
- 近战武器(melee)：需要靠近敌人，dist < 5
- 远程武器(ranged)：保持距离攻击
- 魔法武器(magic)：需要蓝量
- 优先选damage高的武器

生存：
- 血量低于30%立刻撤退（系统会自动中断）
- 熔岩(lava)附近立刻向上或反向撤退
- 治疗药水有冷却，不要频繁使用

## 示例

{"思考": "地形平坦，向右探索", "控制": {"right": true}, "持续秒数": 5.0}
{"思考": "前方有墙，跳跃越过", "控制": {"right": true, "jump": true}, "持续秒数": 0.5}
{"思考": "附近有敌人，切换到近战武器攻击", "控制": {"selected_slot": 0, "use_item": true}, "持续秒数": 2.0}
{"思考": "血量低，快速治疗", "控制": {"quick_heal": true}, "持续秒数": 0.1}
{"思考": "附近有掉落物，拾取", "控制": {"loot_all": true}, "持续秒数": 0.1}
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
