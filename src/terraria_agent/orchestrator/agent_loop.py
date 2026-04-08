from __future__ import annotations

import threading
import time
import traceback
from typing import Protocol

from terraria_agent.cerebellum.screen_capture import ScreenCapture
from terraria_agent.cerebellum.vision import UIVisionDetector
from terraria_agent.hand.controller import HandController
from terraria_agent.hud.state_bridge import HUDSnapshot, StateBridge
from terraria_agent.models.actions import GameAction
from terraria_agent.models.game_state import GameState, Player
from terraria_agent.models.task_queue import Task, TaskPriority, TaskQueue
from terraria_agent.spinal_cord.bt.core import Status
from terraria_agent.spinal_cord.context import TickContext
from terraria_agent.spinal_cord.trees.root import build_root_tree


class Capturer(Protocol):
    def capture(self) -> object: ...


class Detector(Protocol):
    def detect(self, frame) -> GameState: ...


class Hand(Protocol):
    def execute(self, actions: list[GameAction]) -> None: ...
    def release_all(self) -> None: ...
    @property
    def key_state(self): ...


def _empty_state() -> GameState:
    return GameState(player=Player(hp=0, max_hp=1, pos=(0.0, 0.0)))


def _action_summary(action: GameAction) -> str:
    parts = [action.action.value]
    if action.direction:
        parts.append(action.direction)
    if action.slot is not None:
        parts.append(f"slot={action.slot}")
    if action.item:
        parts.append(action.item)
    return " ".join(parts)


class AgentOrchestrator:
    """Background-thread agent loop. Reads from StateBridge, publishes snapshots back."""

    def __init__(
        self,
        bridge: StateBridge,
        tick_rate: float = 5.0,
        capture: Capturer | None = None,
        detector: Detector | None = None,
        hand: Hand | None = None,
        bt_root=None,
    ) -> None:
        self._bridge = bridge
        self._tick_rate = tick_rate
        self._interval = 1.0 / tick_rate
        self._capture = capture if capture is not None else ScreenCapture()
        self._detector = detector if detector is not None else UIVisionDetector()
        self._hand = hand if hand is not None else HandController(
            mouse_control_flag=bridge.is_mouse_control_enabled,
        )
        self._bt_root = bt_root if bt_root is not None else build_root_tree()
        self._task_queue = TaskQueue(goal="idle", task_queue=[])
        self._tick_count = 0
        self._tps = 0.0
        self._last_tick_time = 0.0
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="AgentLoop", daemon=True)
        self._thread.start()
        self._bridge.log("[agent] started")

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        try:
            self._hand.release_all()
        except Exception as e:
            self._bridge.log(f"[agent] release_all error: {e}")
        self._bridge.log("[agent] stopped")

    def _loop(self) -> None:
        while self._running:
            start = time.monotonic()
            try:
                self.tick_once()
            except Exception:
                self._bridge.log(f"[agent] tick error: {traceback.format_exc(limit=2)}")
            elapsed = time.monotonic() - start
            sleep_for = self._interval - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)

    def tick_once(self) -> None:
        self._tick_count += 1
        now = time.monotonic()
        if self._last_tick_time > 0:
            dt = now - self._last_tick_time
            if dt > 0:
                self._tps = 0.7 * self._tps + 0.3 * (1.0 / dt)
        self._last_tick_time = now

        for cmd in self._bridge.drain_commands():
            self._handle_command(cmd)

        if self._bridge.is_paused():
            self._publish(_empty_state(), [], "paused", "")
            return

        frame = self._capture.capture()
        game_state = self._detector.detect(frame)

        ctx = TickContext(
            game_state=game_state,
            task_queue=self._task_queue,
            dt=self._interval,
        )
        try:
            status = self._bt_root.tick(ctx)
        except Exception:
            self._bridge.log(f"[bt] tick error: {traceback.format_exc(limit=2)}")
            return

        try:
            self._hand.execute(ctx.action_buffer)
        except Exception:
            self._bridge.log(f"[hand] execute error: {traceback.format_exc(limit=2)}")

        branch = " > ".join(ctx.bt_trace) if ctx.bt_trace else "Root"
        self._publish(game_state, ctx.action_buffer, status.value, branch)

    def _publish(
        self,
        game_state: GameState,
        action_buffer: list[GameAction],
        bt_status: str,
        branch: str,
    ) -> None:
        try:
            held = self._hand.key_state.held_keys
        except Exception:
            held = frozenset()
        snap = HUDSnapshot(
            hp=game_state.player.hp,
            max_hp=max(game_state.player.max_hp, 1),
            danger_level=game_state.player.danger_level,
            hp_trend=game_state.player.hp_trend,
            selected_slot=game_state.player.selected_slot,
            buffs=tuple(game_state.player.buffs),
            inventory_open=game_state.player.inventory_open,
            active_bt_branch=branch,
            bt_status=bt_status,
            action_buffer=tuple(_action_summary(a) for a in action_buffer),
            held_keys=held,
            current_goal=self._task_queue.goal,
            task_queue_summary=tuple(
                f"[{t.priority.value}] {t.trigger}: {t.action}" for t in self._task_queue.task_queue
            ),
            tick_count=self._tick_count,
            tps=self._tps,
            timestamp=time.time(),
        )
        self._bridge.publish_snapshot(snap)

    def _handle_command(self, cmd: str) -> None:
        text = cmd.strip()
        if not text:
            return
        lower = text.lower()
        if lower in ("pause", "stop"):
            self._bridge.set_paused(True)
            self._bridge.log("[cmd] paused")
            return
        if lower in ("resume", "go"):
            self._bridge.set_paused(False)
            self._bridge.log("[cmd] resumed")
            return
        if lower == "clear":
            self._task_queue = TaskQueue(goal=self._task_queue.goal, task_queue=[])
            self._bridge.log("[cmd] task queue cleared")
            return
        if lower.startswith("goal:"):
            goal = text.split(":", 1)[1].strip()
            self._task_queue = TaskQueue(goal=goal or "idle", task_queue=list(self._task_queue.task_queue))
            self._bridge.log(f"[cmd] goal set to {goal!r}")
            return
        if lower.startswith("task:"):
            self._add_task(text.split(":", 1)[1].strip())
            return
        self._bridge.log(f"[cmd] unknown: {text}")

    def _add_task(self, body: str) -> None:
        parts = body.split()
        if len(parts) < 2:
            self._bridge.log("[cmd] task format: task: <trigger> <action> [priority]")
            return
        trigger, action = parts[0], parts[1]
        priority = TaskPriority.BASELINE
        if len(parts) >= 3:
            try:
                priority = TaskPriority(parts[2].lower())
            except ValueError:
                self._bridge.log(f"[cmd] unknown priority {parts[2]!r}, using baseline")
        self._task_queue.task_queue.append(Task(trigger=trigger, action=action, priority=priority))
        self._bridge.log(f"[cmd] task added: {trigger}/{action} ({priority.value})")
