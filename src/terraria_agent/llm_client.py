from __future__ import annotations

import json
import os
import re

from openai import OpenAI

_SKILL_LIST = """\
explore_right, explore_left, descend,
retreat_right, retreat_left, loot, heal,
fight_nearest, fight_moving_right, fight_moving_left,
dig_forward, build_bridge, pillar_jump,
open_chest, loot_chest\
"""

_SYSTEM = f"""\
你是一个控制 Terraria 玩家的 Commander AI。你的目标是探索世界、生存、收集资源。

每次收到当前游戏状态后，输出一条指令。

## 输出格式（三选一）

方式一：目标导向（有明确对象时优先用）
{{"思考": "...", "goal": "<目标名>", "target": {{"type": "<对象类型>", "rel_x": N, "rel_y": N}}, "timeout": N}}

方式二：预定义技能
{{"思考": "...", "skill": "<技能名>", "持续秒数": N}}

方式三：内联控制（技能库不够用时）
{{"思考": "...", "控制": {{...}}, "持续秒数": N}}

## 可用目标（方式一）

- open_chest：走到箱子旁边，自动开箱并掏空。target type="chest"
- chop_tree：走到树旁边，持续砍伐直到树消失。target type="tree"

target 的 rel_x/rel_y 来自 objects 列表的 rel 字段（相对玩家中心的 tile 偏移）。
timeout 建议：open_chest 15，chop_tree 30。

## 可用技能（方式二）

- explore_right/left：向右/左探索，mod自动处理跳跃
- descend：下洞穴
- retreat_right/left：撤退
- fight_nearest：自动瞄准攻击最近敌人
- fight_moving_right/left：边移动边攻击
- loot：拾取附近掉落物
- heal：使用治疗药水
- craft：制作物品。需额外字段 item_id（从可制作列表取）和 amount（数量）

## Terraria 游戏规则

- 树木不挡路，玩家可以直接穿过
- terrain_ahead=block_wall 或 pit：继续 explore，mod自动跳跃处理
- 血量低于30%系统自动中断撤退，不需要你处理
- 熔岩(lava)附近立刻 retreat
- trees_chopped=N/2：已自动砍了N棵高树，达到2棵后不要再主动砍树

## 示例

{{"思考": "发现箱子在右方12格，走过去开箱", "goal": "open_chest", "target": {{"type": "chest", "rel_x": 12, "rel_y": 0}}, "timeout": 15}}
{{"思考": "发现高树在左方8格，砍树获取木材", "goal": "chop_tree", "target": {{"type": "tree", "rel_x": -8, "rel_y": 0}}, "timeout": 30}}
{{"思考": "地形平坦，向右探索", "skill": "explore_right", "持续秒数": 20.0}}
{{"思考": "有敌人，攻击", "skill": "fight_nearest", "持续秒数": 5.0}}
{{"思考": "有木材可制作木平台", "skill": "craft", "item_id": 94, "amount": 20}}
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class LLMClient:
    def __init__(self) -> None:
        self._client = OpenAI(
            api_key=os.environ.get("COMMANDER_API_KEY", ""),
            base_url=os.environ.get("COMMANDER_API_URL", "https://api.openai.com/v1"),
        )
        self._model = os.environ.get("COMMANDER_MODEL", "gpt-4o")

    def decide(self, state_text: str) -> dict:
        import time as _time
        t0 = _time.monotonic()
        print(f"[commander] 调用 {self._model}...")
        msg = self._client.chat.completions.create(
            model=self._model,
            max_tokens=256,
            timeout=30,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": state_text},
            ],
        )
        latency = _time.monotonic() - t0
        raw = msg.choices[0].message.content.strip()
        usage = msg.usage
        print(f"[commander] {latency:.1f}s | prompt={usage.prompt_tokens} completion={usage.completion_tokens} | {raw!r}")

        m = _JSON_RE.search(raw)
        if not m:
            return {}
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            return {}
