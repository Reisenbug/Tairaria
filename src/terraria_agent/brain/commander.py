from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from terraria_agent.brain.events import BrainEvent, EventBuffer, Severity
from terraria_agent.brain.views import build_commander_view
from terraria_agent.models.game_state import GameState
from terraria_agent.models.task_queue import TaskQueue


_DEFAULT_BASE_URL = os.environ.get("COMMANDER_API_URL", "https://api.openai.com/v1")
_DEFAULT_MODEL = os.environ.get("COMMANDER_MODEL", "deepseek-reasoner")
_DEFAULT_API_KEY = os.environ.get("COMMANDER_API_KEY", "")


SYSTEM_PROMPT = """\
You are the Terraria strategic commander. You set long-term goals for the agent.
A faster tactical AI handles moment-to-moment decisions; you set the big picture.

Input shape:
- hp, max_hp, pos, biome: current snapshot
- goal: current active goal
- goal_achieved: bool
- have_categories: inventory categories owned (e.g. ["weapon","pickaxe","axe","torch"])
- recent_tactical_decisions: last 5 moves by the tactical layer
- strategic_events: big events (died, new_biome, goal_achieved, boss_defeated)

Rules:
- Return ONLY valid JSON, no markdown, no prose.
- Default: {"action": "noop"} — keep current goal.
- Change goals sparingly. Only when the current goal is achieved, unachievable,
  or a strategic event demands shift.

Action schema:
- {"action": "noop"}
- {"action": "set_goal", "goal": "short description"}
- {"action": "set_stop_biome", "biome": "jungle"|"ocean"|...}
"""


@dataclass
class CommanderConfig:
    base_url: str = _DEFAULT_BASE_URL
    model: str = _DEFAULT_MODEL
    api_key: str = _DEFAULT_API_KEY
    call_interval: float = 120.0
    timeout: float = 30.0


@dataclass
class Commander:
    config: CommanderConfig = field(default_factory=CommanderConfig)
    _last_call: float = 0.0
    _inflight: Any = field(default=None, repr=False)
    _ready_decision: dict | None = field(default=None, repr=False)
    _lock: Any = field(default=None, repr=False)
    _opener: Any = field(default=None, repr=False)
    _warned_no_key: bool = False
    _recent_tactical: deque = field(default_factory=lambda: deque(maxlen=10))
    last_input: str = ""
    last_output: str = ""

    def __post_init__(self):
        self._opener = urllib.request.build_opener()
        self._lock = threading.Lock()

    def record_tactical_decision(self, decision: dict) -> None:
        action = decision.get("action", "?")
        summary = {"action": action, "t": time.time()}
        for key in ("direction", "goal", "reason", "preference", "slot"):
            if key in decision:
                summary[key] = decision[key]
        self._recent_tactical.append(summary)

    def should_call(self, buffer: EventBuffer) -> bool:
        if self._inflight is not None and self._inflight.is_alive():
            return False
        strategic_recent = buffer.recent_at_least(Severity.STRATEGIC, limit=5)
        for e in strategic_recent:
            if e.timestamp > self._last_call:
                return True
        return (time.monotonic() - self._last_call) >= self.config.call_interval

    def maybe_start(self, gs: GameState, task_queue: TaskQueue, buffer: EventBuffer) -> bool:
        if not self.config.api_key:
            if not self._warned_no_key:
                self._warned_no_key = True
            return False
        if self._inflight is not None and self._inflight.is_alive():
            return False

        strategic = buffer.recent_at_least(Severity.STRATEGIC, limit=10)
        now = time.time()
        recent_decisions = [
            {**d, "t": round(d["t"] - now, 1)} for d in self._recent_tactical
        ]
        view = build_commander_view(
            gs, strategic, recent_decisions, task_queue.goal, task_queue.goal_achieved
        )
        user_msg = json.dumps(view, ensure_ascii=False)
        self.last_input = user_msg

        self._inflight = threading.Thread(
            target=self._run_chat, args=(user_msg,), name="CommanderCall", daemon=True,
        )
        self._inflight.start()
        return True

    def _run_chat(self, user_msg: str) -> None:
        try:
            result, raw = self._chat(user_msg)
            with self._lock:
                self.last_output = raw
                self._ready_decision = result
                self._last_call = time.monotonic()
        except Exception as e:
            with self._lock:
                self.last_output = f"ERROR: {e}"
                self._last_call = time.monotonic()

    def poll_decision(self) -> dict | None:
        with self._lock:
            d = self._ready_decision
            self._ready_decision = None
            return d

    def _chat(self, user_msg: str) -> tuple[dict, str]:
        body = json.dumps({
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.2,
            "max_tokens": 400,
        }).encode()

        req = urllib.request.Request(
            f"{self.config.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
        )

        with self._opener.open(req, timeout=self.config.timeout) as resp:
            data = json.loads(resp.read())

        content = data["choices"][0]["message"]["content"]
        raw = content.strip()
        stripped = raw
        if stripped.startswith("```"):
            stripped = stripped.split("\n", 1)[-1].rsplit("```", 1)[0]
        return json.loads(stripped), raw


def apply_commander_decision(decision: dict, task_queue: TaskQueue) -> str | None:
    action = decision.get("action")
    if action == "noop":
        return None
    if action == "set_goal":
        goal = decision.get("goal", task_queue.goal)
        task_queue.goal = goal
        task_queue.goal_achieved = False
        return f"goal → {goal}"
    if action == "set_stop_biome":
        biome = decision.get("biome")
        task_queue.stop_biome = biome
        return f"stop_biome → {biome}"
    return f"unknown action: {action}"
