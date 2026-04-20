from __future__ import annotations

import json
import os
import pathlib
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from terraria_agent.brain.events import BrainEvent, EventBuffer, Severity
from terraria_agent.brain.views import build_view
from terraria_agent.models.game_state import GameState
from terraria_agent.models.goal import Goal
from terraria_agent.models.task_queue import Task, TaskPriority, TaskQueue


def _load_dotenv() -> None:
    env_path = pathlib.Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


_load_dotenv()

_DEFAULT_BASE_URL = os.environ.get("TACTICIAN_API_URL", "https://api.openai.com/v1")
_DEFAULT_MODEL = os.environ.get("TACTICIAN_MODEL", "deepseek-v3.2")
_DEFAULT_API_KEY = os.environ.get("TACTICIAN_API_KEY", "")

SYSTEM_PROMPT = """\
You are a Terraria tactical AI. BT (behavior tree) handles walking, mining, swimming, combat automatically.
You get a scenario-filtered view of state + recent events. Decide what to override.

Input shape: {"scenario": "walking"|"combat"|"low_hp"|"terrain", "hp", "pos", "dir", "biome", ...scenario-specific, "events": [...]}

Scenario-specific fields:
- walking: grid_ahead (16x10 ASCII), on_ground, have (inventory categories), targets
- combat: enemies, weapons (inv), buffs
- low_hp: enemies, consumables (inv), buffs
- terrain: grid_ahead (21x13 ASCII), movement (jump/speed/no_fall_dmg), have

grid_ahead: multiline ASCII map. P=player feet column, #=solid, ~=water, !=lava, .=air, ?=unknown.
Rows go top→bottom (above player → below). Cols go back→forward (back of player → ahead, flipped for dir).
Walking grid: 3 cols behind + P + 12 cols ahead; 5 rows above + 4 rows below feet.
Reading: ground under P is row just below P. Gap ahead = "." where "#" should be. Cavern = large "." block
extending right+down. Fall >25 tiles (no "#" within 25 rows) = death unless no_fall_dmg.
Jump clears ~6 up / ~4 across. If ahead has drop ≥3 rows × ≥2 cols, reflex already stops walking —
decide change_direction or emit a detour set_tasks/set_active_goal.

Rules:
- Return ONLY valid JSON, no markdown, no prose.
- Default: {"action": "noop"} — BT continues as-is.
- NEVER include trigger="default" in set_tasks. The baseline walk task is system-managed.

Action schema (you do NOT set strategic goals — commander handles that):
- {"action": "noop"}
- {"action": "change_direction", "direction": "left"|"right"}
- {"action": "set_tasks", "tasks": [{"trigger": "...", "action": "...", "priority": "baseline"|"high"|"critical"}]}
- {"action": "set_active_goal", "goal": {"kind": "chop_tree", "target_tile": [tx, ty], "ttl": 10}}
- {"action": "clear_active_goal"}
- {"action": "retreat", "reason": "..."}
- {"action": "use_item", "slot": N}
- {"action": "select_weapon", "preference": "melee"|"ranged"|"best_dps"}

active_goal pins a fine-grained target across ticks (prevents oscillation) AND is
the ONLY way to trigger object-focused behavior now (BT no longer auto-triggers).
Kinds: chop_tree. target_tile is the object's tile_pos from walking-scenario targets[].
When `targets` contains a tree and you want it chopped → emit set_active_goal(chop_tree, target_tile).
BT will then MoveToObject → ChopBigTree → pickup automatically. Without a goal,
BT only walks + reflexes — it will walk past trees.
"""


@dataclass
class TacticianConfig:
    base_url: str = _DEFAULT_BASE_URL
    model: str = _DEFAULT_MODEL
    api_key: str = _DEFAULT_API_KEY
    call_interval: float = 5.0
    timeout: float = 20.0


@dataclass
class Tactician:
    config: TacticianConfig = field(default_factory=TacticianConfig)
    _last_call: float = 0.0
    _pending_events: list[BrainEvent] = field(default_factory=list)
    _opener: Any = field(default=None, repr=False)
    _inflight: Any = field(default=None, repr=False)
    _ready_decision: dict | None = field(default=None, repr=False)
    _lock: Any = field(default=None, repr=False)
    last_input: str = ""
    last_output: str = ""
    last_latency: float = 0.0
    _latencies: list[float] = field(default_factory=list)
    _call_start: float = 0.0

    def __post_init__(self):
        self._opener = urllib.request.build_opener()
        self._lock = threading.Lock()

    def collect_events(self, events: list[BrainEvent]) -> None:
        self._pending_events.extend(events)

    def should_call(self) -> bool:
        if self._inflight is not None and self._inflight.is_alive():
            return False
        if self._pending_events:
            return True
        return (time.monotonic() - self._last_call) >= self.config.call_interval

    def maybe_start(self, gs: GameState, task_queue: TaskQueue, buffer: EventBuffer | None = None) -> bool:
        if not self.config.api_key:
            return False
        if self._inflight is not None and self._inflight.is_alive():
            return False

        recent = buffer.recent_at_least(Severity.TACTICAL, limit=10) if buffer else self._pending_events
        view = build_view(gs, recent, task_queue.goal, task_queue.goal_achieved)
        if task_queue.active_goal is not None:
            g = task_queue.active_goal
            view["active_goal"] = {
                "kind": g.kind,
                "target_tile": list(g.target_tile),
                "attempts": g.attempts,
            }
        self._pending_events.clear()
        user_msg = json.dumps(view, ensure_ascii=False)
        self.last_input = user_msg
        from terraria_agent.diag_log import diag
        diag("tactician_input", user_msg)
        if "grid_ahead" in view:
            diag("tactician_grid", f"scenario={view.get('scenario')} dir={view.get('dir')}\n{view['grid_ahead']}")

        self._call_start = time.monotonic()
        self._inflight = threading.Thread(
            target=self._run_chat, args=(user_msg,), name="TacticianCall", daemon=True,
        )
        self._inflight.start()
        return True

    def _run_chat(self, user_msg: str) -> None:
        from terraria_agent.diag_log import diag
        start = self._call_start
        try:
            result, raw = self._chat(user_msg)
            end = time.monotonic()
            latency = end - start
            with self._lock:
                self.last_output = raw
                self._ready_decision = result
                self._last_call = end
                self.last_latency = latency
                self._latencies.append(latency)
                if len(self._latencies) > 100:
                    self._latencies.pop(0)
            diag("tactician_output", raw)
            diag("tactician_latency", f"ok latency={latency:.2f}s interval={self.config.call_interval}s")
        except Exception as e:
            end = time.monotonic()
            latency = end - start
            with self._lock:
                self.last_output = f"ERROR: {e}"
                self._last_call = end
                self.last_latency = latency
            diag("tactician_output", f"ERROR: {e}")
            diag("tactician_latency", f"err latency={latency:.2f}s err={type(e).__name__}:{e}")

    def latency_stats(self) -> dict:
        with self._lock:
            xs = list(self._latencies)
        if not xs:
            return {"n": 0}
        xs_sorted = sorted(xs)
        n = len(xs_sorted)
        return {
            "n": n,
            "mean": sum(xs_sorted) / n,
            "p50": xs_sorted[n // 2],
            "p95": xs_sorted[min(n - 1, int(n * 0.95))],
            "max": xs_sorted[-1],
        }

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
            "temperature": 0.3,
            "max_tokens": 256,
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
        content = raw
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0]
        return json.loads(content), raw


def apply_decision(decision: dict, task_queue: TaskQueue) -> str | None:
    action = decision.get("action")
    if action == "noop":
        return None

    if action == "change_direction":
        direction = decision.get("direction", "right")
        for task in task_queue.task_queue:
            if task.trigger == "default":
                task.action = f"move_{direction}"
                return f"direction → {direction}"
        return None

    if action == "set_tasks":
        raw_tasks = decision.get("tasks", [])
        new_tasks = []
        for t in raw_tasks:
            try:
                trigger = t["trigger"]
                if trigger == "default":
                    continue
                new_tasks.append(Task(
                    trigger=trigger,
                    action=t["action"],
                    priority=TaskPriority(t.get("priority", "baseline")),
                    params=t.get("params", {}),
                ))
            except (KeyError, ValueError):
                continue
        preserved = [t for t in task_queue.task_queue if t.trigger == "default"]
        non_default_existing = [t for t in task_queue.task_queue if t.trigger != "default"]
        if new_tasks:
            task_queue.task_queue = preserved + new_tasks
            return f"tasks merged (+{len(new_tasks)}, kept {len(preserved)} default)"
        if non_default_existing:
            task_queue.task_queue = preserved
            return f"tasks cleared (kept {len(preserved)} default)"
        return None

    if action == "set_goal":
        return "rejected: set_goal is commander-only"

    if action == "set_active_goal":
        raw = decision.get("goal") or {}
        try:
            tt = raw.get("target_tile")
            if not (isinstance(tt, (list, tuple)) and len(tt) == 2):
                return "rejected: set_active_goal needs target_tile [tx,ty]"
            goal = Goal(
                kind=raw.get("kind", ""),
                target_tile=(int(tt[0]), int(tt[1])),
                ttl=float(raw.get("ttl", 10.0)),
                max_attempts=int(raw.get("max_attempts", 5)),
                parent_strategic_goal=task_queue.goal,
            )
        except (TypeError, ValueError) as e:
            return f"rejected: set_active_goal parse error: {e}"
        task_queue.active_goal = goal
        return f"active_goal ← {goal.kind}@{goal.target_tile}"

    if action == "clear_active_goal":
        if task_queue.active_goal is None:
            return None
        old = task_queue.active_goal
        task_queue.active_goal = None
        return f"active_goal cleared ({old.kind}@{old.target_tile})"

    if action == "retreat":
        for task in task_queue.task_queue:
            if task.trigger == "default":
                current = task.action
                task.action = "move_left" if "right" in current else "move_right"
                return f"retreat: {decision.get('reason', '')}"
        return None

    return f"unknown action: {action}"
