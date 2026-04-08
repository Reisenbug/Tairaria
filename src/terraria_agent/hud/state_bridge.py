from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class HUDSnapshot:
    hp: int = 0
    max_hp: int = 1
    danger_level: str = "safe"
    hp_trend: str = "stable"
    selected_slot: int = 0
    buffs: tuple[str, ...] = ()
    inventory_open: bool = False

    active_bt_branch: str = ""
    bt_status: str = ""
    action_buffer: tuple[str, ...] = ()

    held_keys: frozenset[str] = field(default_factory=frozenset)

    current_goal: str = "idle"
    task_queue_summary: tuple[str, ...] = ()

    tick_count: int = 0
    tps: float = 0.0
    timestamp: float = 0.0


class StateBridge:
    """Thread-safe bridge between the agent loop (background thread) and the HUD (main thread)."""

    def __init__(self, log_capacity: int = 500) -> None:
        self._lock = threading.Lock()
        self._snapshot: HUDSnapshot | None = None
        self._command_queue: queue.Queue[str] = queue.Queue()
        self._log_queue: queue.Queue[str] = queue.Queue(maxsize=log_capacity)
        self._paused = False
        self._visible = True

    def publish_snapshot(self, snapshot: HUDSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot

    def get_snapshot(self) -> HUDSnapshot | None:
        with self._lock:
            return self._snapshot

    def send_command(self, text: str) -> None:
        text = text.strip()
        if text:
            self._command_queue.put(text)

    def drain_commands(self) -> list[str]:
        out: list[str] = []
        while True:
            try:
                out.append(self._command_queue.get_nowait())
            except queue.Empty:
                break
        return out

    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        try:
            self._log_queue.put_nowait(line)
        except queue.Full:
            try:
                self._log_queue.get_nowait()
                self._log_queue.put_nowait(line)
            except queue.Empty:
                pass

    def drain_logs(self) -> list[str]:
        out: list[str] = []
        while True:
            try:
                out.append(self._log_queue.get_nowait())
            except queue.Empty:
                break
        return out

    def toggle_pause(self) -> None:
        with self._lock:
            self._paused = not self._paused

    def set_paused(self, value: bool) -> None:
        with self._lock:
            self._paused = value

    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    def set_mouse_control(self, value: bool) -> None:
        with self._lock:
            self._mouse_control = value

    def is_mouse_control_enabled(self) -> bool:
        with self._lock:
            return getattr(self, "_mouse_control", True)

    def toggle_visibility(self) -> None:
        with self._lock:
            self._visible = not self._visible

    def is_visible(self) -> bool:
        with self._lock:
            return self._visible
