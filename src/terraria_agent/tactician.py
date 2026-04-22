from __future__ import annotations

import json
import os
import re
import threading

from openai import OpenAI

_SYSTEM = """\
你是 Terraria 玩家的战略规划 AI（Tactician）。你负责制定和更新长期目标。
执行层（Commander）会根据你的目标实时决策具体动作，你不需要关心细节。

每分钟收到一次宏观游戏状态，输出当前目标。

## 输出格式

{"思考": "...", "目标": "简短目标描述"}

如果当前目标仍然合适，可以保持不变（原样输出）。

## 目标示例

- "向右探索，收集掉落物"
- "寻找并打开箱子"
- "击败附近敌人后继续探索"
- "收集足够木材用于制作"
- "探索地下洞穴"
- "避开危险区域，优先生存"

## Terraria 进度参考

早期目标优先级：生存 > 收集资源 > 探索 > 击败Boss
- 没有武器时避免战斗
- 血量低时优先撤退和治疗
- 探索新生物群系前确保装备足够

## 规则

- 目标要简短（10字以内），具体可执行
- 不要制定无法完成的目标（如"击败Boss"但没有武器）
- 根据背包和状态判断当前最优目标
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
            raw = msg.choices[0].message.content.strip()
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
