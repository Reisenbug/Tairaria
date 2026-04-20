from __future__ import annotations

import threading
import time
import traceback
from typing import Protocol

from terraria_agent.cerebellum.screen_capture import ScreenCapture
from terraria_agent.cerebellum.vision import UIVisionDetector
from terraria_agent.brain.commander import Commander, apply_commander_decision
from terraria_agent.brain.events import BrainEvent, EventBuffer, Severity
from terraria_agent.brain.tactician import Tactician, TacticianConfig, apply_decision
from terraria_agent.hand.arbiter import arbitrate
from terraria_agent.hand.controller import HandController
from terraria_agent.hand.hotbar_organizer import organize_hotbar
from terraria_agent.hand.mod_controller import ModController
from terraria_agent.hud.state_bridge import HUDSnapshot, StateBridge
from terraria_agent.models.actions import GameAction
from terraria_agent.models.game_state import GameState, Player
from terraria_agent.models.goal import Goal
from terraria_agent.models.task_queue import Task, TaskPriority, TaskQueue
from terraria_agent.spinal_cord.actions.movement import MineForward
from terraria_agent.spinal_cord.bt.core import Node, Status
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
        self._hand = hand if hand is not None else ModController(
            mouse_control_flag=bridge.is_mouse_control_enabled,
        )
        self._bt_root = bt_root if bt_root is not None else build_root_tree()
        self._tactician = Tactician()
        self._commander = Commander()
        self._event_buffer = EventBuffer(maxlen=50)
        self._last_tactician_msg = ""
        self._last_commander_msg = ""
        self._commander_warned = False
        self._task_queue = TaskQueue(goal="idle", task_queue=[])
        self._looted_chests: set[tuple[int, int]] = set()
        self._smart_cursor = False
        self._oneshot: Node | None = None
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

        swaps = organize_hotbar(game_state.inventory_slots)
        if swaps:
            self._bridge.log(f"[hotbar] {len(swaps)} swaps")

        tq = self._task_queue
        if (
            not tq.goal_achieved
            and tq.stop_biome is not None
            and game_state.biome == tq.stop_biome
        ):
            tq.goal_achieved = True
            self._bridge.log(f"[goal] reached biome={tq.stop_biome} — continuing")

        self._evaluate_active_goal(game_state)
        ctx = TickContext(
            game_state=game_state,
            task_queue=self._task_queue,
            dt=self._interval,
            smart_cursor=game_state.smart_cursor,
            looted_chests=self._looted_chests,
            active_goal=self._task_queue.active_goal,
        )
        oneshot = self._oneshot
        self._oneshot = None
        if oneshot is not None:
            try:
                status = oneshot.tick(ctx)
                self._bridge.log(f"[oneshot] {oneshot.name} -> {status.value}")
            except Exception:
                self._bridge.log(f"[oneshot] tick error: {traceback.format_exc(limit=2)}")
                return
        else:
            try:
                status = self._bt_root.tick(ctx)
            except Exception:
                self._bridge.log(f"[bt] tick error: {traceback.format_exc(limit=2)}")
                return

        if ctx.brain_events:
            self._event_buffer.extend(ctx.brain_events)
            self._tactician.collect_events(ctx.brain_events)

        if not self._commander.config.api_key and not self._commander_warned:
            self._commander_warned = True
            self._bridge.log("[commander] no API key set — strategic layer disabled")
        if self._commander.should_call(self._event_buffer):
            self._commander.maybe_start(game_state, self._task_queue, self._event_buffer)
        cmd_decision = self._commander.poll_decision()
        if cmd_decision:
            try:
                cmsg = apply_commander_decision(cmd_decision, self._task_queue)
                if cmsg:
                    self._last_commander_msg = cmsg
                    self._bridge.log(f"[commander] {cmsg}")
            except Exception:
                self._bridge.log(f"[commander] error: {traceback.format_exc(limit=2)}")

        if self._tactician.should_call():
            self._tactician.maybe_start(game_state, self._task_queue, self._event_buffer)
        decision = self._tactician.poll_decision()
        if decision:
            try:
                msg = apply_decision(decision, self._task_queue)
                if msg:
                    self._last_tactician_msg = msg
                    self._bridge.log(f"[tactician] {msg}")
                self._commander.record_tactical_decision(decision)
            except Exception:
                self._bridge.log(f"[tactician] error: {traceback.format_exc(limit=2)}")

        self._task_queue.active_goal = ctx.active_goal

        kept, dropped = arbitrate(ctx.action_buffer)
        if dropped:
            reasons = ", ".join(f"{a.action.value}×{r.value}" for a, r in dropped)
            self._bridge.log(f"[arbiter] dropped: {reasons}")
        ctx.action_buffer = kept

        try:
            self._hand.execute(ctx.action_buffer)
        except Exception:
            self._bridge.log(f"[hand] execute error: {traceback.format_exc(limit=2)}")

        branch = " > ".join(ctx.bt_trace) if ctx.bt_trace else "Root"
        self._publish(game_state, ctx.action_buffer, status.value, branch)

    def _evaluate_active_goal(self, game_state: GameState) -> None:
        goal = self._task_queue.active_goal
        if goal is None:
            return
        if goal.kind == "open_chest" and goal.target_tile in self._looted_chests:
            self._bridge.log(f"[goal] open_chest@{goal.target_tile} completed (looted)")
            self._task_queue.active_goal = None
            self._tactician.collect_events([BrainEvent(
                type="goal_completed",
                details={"kind": goal.kind, "target_tile": list(goal.target_tile)},
                severity=Severity.TACTICAL,
                timestamp=time.time(),
            )])
            return
        target_present = any(o.tile_pos == goal.target_tile for o in game_state.objects)
        if not target_present:
            self._bridge.log(f"[goal] {goal.kind}@{goal.target_tile} completed (target gone)")
            self._task_queue.active_goal = None
            self._tactician.collect_events([BrainEvent(
                type="goal_completed",
                details={"kind": goal.kind, "target_tile": list(goal.target_tile)},
                severity=Severity.TACTICAL,
                timestamp=time.time(),
            )])
            return
        if goal.expired():
            self._bridge.log(f"[goal] {goal.kind}@{goal.target_tile} aborted (ttl)")
            self._task_queue.active_goal = None
            self._tactician.collect_events([BrainEvent(
                type="goal_aborted",
                details={"kind": goal.kind, "target_tile": list(goal.target_tile), "reason": "ttl"},
                severity=Severity.TACTICAL,
                timestamp=time.time(),
            )])
            return
        if goal.exhausted():
            self._bridge.log(f"[goal] {goal.kind}@{goal.target_tile} aborted (attempts>{goal.max_attempts})")
            self._task_queue.active_goal = None
            self._tactician.collect_events([BrainEvent(
                type="goal_aborted",
                details={"kind": goal.kind, "target_tile": list(goal.target_tile), "reason": "attempts"},
                severity=Severity.TACTICAL,
                timestamp=time.time(),
            )])
            return

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
            tactician_input=self._tactician.last_input,
            tactician_output=self._tactician.last_output,
            tactician_msg=self._last_tactician_msg,
            tactician_latency=self._format_tactician_latency(),
            commander_input=self._commander.last_input,
            commander_output=self._commander.last_output,
            commander_msg=self._last_commander_msg,
            tick_count=self._tick_count,
            tps=self._tps,
            timestamp=time.time(),
        )
        self._bridge.publish_snapshot(snap)

    def _format_tactician_latency(self) -> str:
        st = self._tactician.latency_stats()
        if st["n"] == 0:
            return "last=— p50=— p95=—"
        return (
            f"last={self._tactician.last_latency:.2f}s "
            f"p50={st['p50']:.2f}s p95={st['p95']:.2f}s "
            f"max={st['max']:.2f}s n={st['n']}"
        )

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
        if lower in ("smart_cursor on", "smartcursor on", "sc on"):
            self._smart_cursor = True
            self._bridge.log("[cmd] smart_cursor=ON")
            return
        if lower in ("smart_cursor off", "smartcursor off", "sc off"):
            self._smart_cursor = False
            self._bridge.log("[cmd] smart_cursor=OFF")
            return
        if lower in ("smart_cursor", "smartcursor", "sc"):
            self._smart_cursor = not self._smart_cursor
            self._bridge.log(f"[cmd] smart_cursor={'ON' if self._smart_cursor else 'OFF'}")
            return
        if lower in ("mine", "mine_forward", "mineforward"):
            self._oneshot = MineForward(name="MineForward(oneshot)")
            self._bridge.log("[cmd] mine_forward queued (next tick)")
            return
        if lower.startswith("goal:"):
            goal = text.split(":", 1)[1].strip()
            self._task_queue = TaskQueue(goal=goal or "idle", task_queue=list(self._task_queue.task_queue))
            self._bridge.log(f"[cmd] goal set to {goal!r}")
            return
        if lower.startswith("task:"):
            self._add_task(text.split(":", 1)[1].strip())
            return
        if lower.startswith("goal_tree:"):
            self._inject_goal("chop_tree", text.split(":", 1)[1].strip())
            return
        if lower == "goal_clear":
            self._task_queue.active_goal = None
            self._bridge.log("[cmd] active_goal cleared")
            return
        self._bridge.log(f"[cmd] unknown: {text}")

    def _inject_goal(self, kind: str, body: str) -> None:
        try:
            tx_str, ty_str = body.split(",", 1)
            tx, ty = int(tx_str.strip()), int(ty_str.strip())
        except ValueError:
            self._bridge.log(f"[cmd] goal format: goal_tree: <tx>,<ty>")
            return
        self._task_queue.active_goal = Goal(kind=kind, target_tile=(tx, ty))
        self._bridge.log(f"[cmd] active_goal set: {kind}@({tx},{ty})")

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
