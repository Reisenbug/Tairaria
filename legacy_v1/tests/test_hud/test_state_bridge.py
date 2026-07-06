from __future__ import annotations

import threading

import pytest

from terraria_agent.hud.state_bridge import HUDSnapshot, StateBridge


class TestStateBridge:
    def test_snapshot_round_trip(self):
        bridge = StateBridge()
        assert bridge.get_snapshot() is None
        snap = HUDSnapshot(hp=50, max_hp=100)
        bridge.publish_snapshot(snap)
        result = bridge.get_snapshot()
        assert result is snap
        assert result.hp == 50

    def test_command_queue_drain(self):
        bridge = StateBridge()
        bridge.send_command("goal: chop trees")
        bridge.send_command("task: tree chop high")
        commands = bridge.drain_commands()
        assert commands == ["goal: chop trees", "task: tree chop high"]
        assert bridge.drain_commands() == []

    def test_send_command_strips_blanks(self):
        bridge = StateBridge()
        bridge.send_command("   ")
        bridge.send_command("")
        assert bridge.drain_commands() == []

    def test_log_queue_formats_and_drains(self):
        bridge = StateBridge()
        bridge.log("hello")
        lines = bridge.drain_logs()
        assert len(lines) == 1
        assert "hello" in lines[0]
        assert bridge.drain_logs() == []

    def test_log_queue_overflow_drops_oldest(self):
        bridge = StateBridge(log_capacity=3)
        for i in range(5):
            bridge.log(f"msg{i}")
        lines = bridge.drain_logs()
        assert len(lines) == 3
        assert "msg4" in lines[-1]

    def test_pause_toggle(self):
        bridge = StateBridge()
        assert not bridge.is_paused()
        bridge.toggle_pause()
        assert bridge.is_paused()
        bridge.set_paused(False)
        assert not bridge.is_paused()

    def test_visibility_toggle(self):
        bridge = StateBridge()
        assert bridge.is_visible()
        bridge.toggle_visibility()
        assert not bridge.is_visible()
        bridge.toggle_visibility()
        assert bridge.is_visible()

    def test_thread_safe_snapshot_updates(self):
        bridge = StateBridge()
        stop = threading.Event()

        def writer():
            i = 0
            while not stop.is_set():
                bridge.publish_snapshot(HUDSnapshot(hp=i % 100, max_hp=100))
                i += 1

        def reader():
            for _ in range(1000):
                bridge.get_snapshot()

        t = threading.Thread(target=writer, daemon=True)
        t.start()
        try:
            reader()
        finally:
            stop.set()
            t.join(timeout=1.0)
        assert bridge.get_snapshot() is not None
