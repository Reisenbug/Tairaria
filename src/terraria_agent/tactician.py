from __future__ import annotations

import json
import os
import re
import threading

from openai import OpenAI

_SYSTEM = """\
你是 Terraria 玩家的战略规划 AI（Tactician）。每分钟收到一次宏观游戏状态，输出当前目标。
执行层（Commander）会根据你的目标实时决策具体动作。

## 输入字段说明

- hp：当前/最大血量
- biome：当前生物群系
- explore_direction：当前探索方向（left/right，无则未确定）
- detected_tiles：周围检测到的特殊方块（hardened_sand=硬化沙，sandstone=沙岩）
- enemies：附近敌人
- inventory：背包物品
- prev_goal：上次目标（用于保持连续性）

## 输出格式

{"思考": "...", "目标": "简短目标描述"}

prev_goal 仍然合适时直接沿用，思考中说明原因。

## 大目标：前往丛林

## 决策优先级

1. hp < 40%：撤退治疗
2. hp < 60% 且有敌人且无药水：撤退
3. 其余：继续探索

## 丛林方向判断

- 无线索时默认向右
- detected_tiles 含 hardened_sand 或 sandstone → 当前方向有丛林，保持
- biome=snow/corruption/crimson → 丛林在反方向，转向（转向后不再反转）
- biome=jungle → 已到达，目标改为"在丛林探索"

## 规则

- 目标简短（10字以内）
- 确定方向后保持，非必要不变更
- 没有武器时不主动战斗
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class Tactician:
    def __init__(self) -> None:
        self._client = OpenAI(
            api_key=os.environ.get("TACTICIAN_API_KEY", ""),
            base_url=os.environ.get("TACTICIAN_API_URL", "https://api.openai.com/v1"),
        )
        self._model = os.environ.get("TACTICIAN_MODEL", "gpt-4o")
        self._goal: str = ""
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def goal(self) -> str:
        with self._lock:
            return self._goal

    def is_idle(self) -> bool:
        return self._thread is None or not self._thread.is_alive()

    def start(self, state_text: str) -> None:
        self._thread = threading.Thread(
            target=self._run, args=(state_text,), daemon=True
        )
        self._thread.start()

    def _run(self, state_text: str) -> None:
        import time as _time
        t0 = _time.monotonic()
        print(f"[tactician] 调用 {self._model}...")
        try:
            msg = self._client.chat.completions.create(
                model=self._model,
                max_tokens=256,
                timeout=60,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": state_text},
                ],
            )
            latency = _time.monotonic() - t0
            raw = (msg.choices[0].message.content or "").strip()
            usage = msg.usage
            print(f"[tactician] {latency:.1f}s | prompt={usage.prompt_tokens} completion={usage.completion_tokens} | {raw!r}")
            m = _JSON_RE.search(raw)
            if m:
                data = json.loads(m.group())
                goal = data.get("目标", "")
                if goal:
                    with self._lock:
                        self._goal = goal
                    print(f"[tactician] 目标更新: {goal!r}")
        except Exception as e:
            print(f"[tactician] 错误: {e}")
