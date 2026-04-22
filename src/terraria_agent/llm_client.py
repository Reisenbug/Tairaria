from __future__ import annotations

import json
import os
import re

from openai import OpenAI

_SYSTEM = """\
你是一个控制 Terraria 玩家的 AI agent。你的目标是探索世界。

默认行为：向右走，探索地图。可以翻越山丘、下洞穴，没有固定目的地。

每次你会收到当前游戏状态，需要输出一条指令，执行层会持续执行该指令直到触发条件满足，然后再来问你下一步。

输出格式为 JSON，必须包含以下字段：
- "思考": 简短描述你的判断（不发给游戏）
- "控制": 持续发给游戏的按键状态，可包含 left/right/up/down/jump/use_item（bool）、selected_slot（0-9）
- "持续秒数": 该指令持续执行的最长秒数（浮点数），时间到后会重新汇报状态给你

示例：
{"思考": "地形平坦，向右走5秒", "控制": {"right": true}, "持续秒数": 5.0}
{"思考": "前方有墙，跳跃", "控制": {"right": true, "jump": true}, "持续秒数": 0.5}
{"思考": "血量危险，撤退", "控制": {"left": true}, "持续秒数": 3.0}

注意：
- jump=true 只需发一帧即可触发跳跃，mod 端会自动处理跳跃高度
- 遇到敌人时选择合适武器攻击（use_item=true）
- 熔岩附近立刻撤退
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
