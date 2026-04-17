from __future__ import annotations

import json
import os
import pathlib
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from terraria_agent.models.game_state import GameState
from terraria_agent.models.task_queue import Task, TaskPriority, TaskQueue
from terraria_agent.spinal_cord.context import BrainEvent


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
You are a Terraria tactical AI. You receive game state and events from the behavior tree (BT).
Your job: decide what to do next by returning a JSON action.

Rules:
- BT handles movement, mining, swimming, combat automatically. You handle decisions BT can't make.
- Be concise. Return ONLY valid JSON, no markdown.
- If nothing needs changing, return {"action": "noop"}

Terrain columns format (terrain_columns_ahead):
- "+N:" means N tiles ahead in facing direction
- Numbers are Y offsets from feet: negative=above, 0=feet level, positive=below
- "solid at [0,1,2]" = ground. "air" = no solid tile (gap/pit). "lava@N"/"water@N" = liquid.
- Player jump_height ~6 tiles up, ~4 tiles across. Fall >25 tiles = death (unless no_fall_dmg).
- Example: +1:[0,1] +2:air +3:air +4:[2,3] = 2-tile wide gap, landing 2 tiles lower.

Available actions:
- {"action": "noop"} — do nothing, BT continues as-is
- {"action": "change_direction", "direction": "left"|"right"}
- {"action": "set_tasks", "tasks": [{"trigger": "...", "action": "...", "priority": "..."}]}
- {"action": "set_goal", "goal": "description"}
- {"action": "retreat", "reason": "..."}
- {"action": "use_item", "slot": N}
- {"action": "select_weapon", "preference": "melee"|"ranged"|"best_dps"}
"""


def _scan_ahead_text(gs: GameState, columns: int = 20) -> str | None:
    tw = gs.tile_window
    if not tw or not tw.rows:
        return None
    p = gs.player
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    feet_y = int((p.pos[1] + p.height) / 16.0)
    sign = 1 if p.direction == "right" else -1

    lines = []
    for i in range(1, columns + 1):
        cx = pcx + sign * i
        rx = cx - tw.origin[0]
        solids = []
        for dy in range(-4, 10):
            wy = feet_y + dy
            ry = wy - tw.origin[1]
            if 0 <= ry < tw.height and 0 <= rx < tw.width:
                col = 0
                for run in tw.rows[ry]:
                    if rx < col + run.count:
                        if run.solid:
                            solids.append(dy)
                        elif run.lava:
                            solids.append(f"lava@{dy}")
                        elif run.water:
                            solids.append(f"water@{dy}")
                        break
                    col += run.count
        if solids:
            lines.append(f"+{i}: {solids}")
        else:
            lines.append(f"+{i}: air")
    return "\n".join(lines)


def _summarize_state(gs: GameState) -> dict[str, Any]:
    p = gs.player
    inv_summary = {}
    for s in gs.inventory_slots:
        if not s.is_empty:
            cat = s.category
            if cat not in inv_summary:
                inv_summary[cat] = []
            inv_summary[cat].append({"name": s.name, "slot": s.slot_index, "stack": s.stack})

    enemies = [
        {"name": e.type, "hp": e.hp, "dist": round(e.distance, 1), "boss": e.boss}
        for e in gs.enemies[:5]
    ]

    result = {
        "hp": p.hp,
        "max_hp": p.max_hp,
        "pos": {"x": round(p.pos[0]), "y": round(p.pos[1])},
        "direction": p.direction,
        "biome": gs.biome,
        "terrain_ahead": gs.terrain_ahead.value,
        "on_ground": p.velocity[1] == 0.0,
        "inventory_by_category": inv_summary,
        "enemies": enemies,
        "nearby_objects": [{"type": o.type, "dist": round(o.distance, 1)} for o in gs.objects[:8]],
        "movement": {
            "jump_height": gs.movement.jump_height,
            "max_run_speed": gs.movement.max_run_speed,
            "no_fall_dmg": gs.movement.no_fall_dmg,
        },
    }

    terrain_text = _scan_ahead_text(gs)
    if terrain_text:
        result["terrain_columns_ahead"] = terrain_text

    return result


def _summarize_events(events: list[BrainEvent]) -> list[dict]:
    return [{"type": e.type, **e.details} for e in events]


@dataclass
class TacticianConfig:
    base_url: str = _DEFAULT_BASE_URL
    model: str = _DEFAULT_MODEL
    api_key: str = _DEFAULT_API_KEY
    call_interval: float = 5.0
    timeout: float = 10.0


@dataclass
class Tactician:
    config: TacticianConfig = field(default_factory=TacticianConfig)
    _last_call: float = 0.0
    _pending_events: list[BrainEvent] = field(default_factory=list)
    _opener: Any = field(default=None, repr=False)

    def __post_init__(self):
        self._opener = urllib.request.build_opener()

    def collect_events(self, events: list[BrainEvent]) -> None:
        self._pending_events.extend(events)

    def should_call(self) -> bool:
        if self._pending_events:
            return True
        return (time.monotonic() - self._last_call) >= self.config.call_interval

    def decide(self, gs: GameState, task_queue: TaskQueue) -> dict | None:
        if not self.config.api_key:
            return None

        state_summary = _summarize_state(gs)
        state_summary["current_goal"] = task_queue.goal
        state_summary["goal_achieved"] = task_queue.goal_achieved

        events = _summarize_events(self._pending_events)
        self._pending_events.clear()

        user_msg = json.dumps({"state": state_summary, "events": events}, ensure_ascii=False)

        try:
            result = self._chat(user_msg)
            self._last_call = time.monotonic()
            return result
        except Exception:
            return None

    def _chat(self, user_msg: str) -> dict | None:
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
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0]
        return json.loads(content)


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
                new_tasks.append(Task(
                    trigger=t["trigger"],
                    action=t["action"],
                    priority=TaskPriority(t.get("priority", "baseline")),
                    params=t.get("params", {}),
                ))
            except (KeyError, ValueError):
                continue
        if new_tasks:
            task_queue.task_queue = new_tasks
            return f"tasks replaced ({len(new_tasks)})"
        return None

    if action == "set_goal":
        task_queue.goal = decision.get("goal", task_queue.goal)
        return f"goal → {task_queue.goal}"

    if action == "retreat":
        for task in task_queue.task_queue:
            if task.trigger == "default":
                current = task.action
                task.action = "move_left" if "right" in current else "move_right"
                return f"retreat: {decision.get('reason', '')}"
        return None

    return f"unknown action: {action}"
