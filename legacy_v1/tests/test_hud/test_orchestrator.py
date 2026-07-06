from __future__ import annotations

import numpy as np
import pytest

from terraria_agent.hud.state_bridge import StateBridge
from terraria_agent.models.actions import ActionType, GameAction
from terraria_agent.models.game_state import GameState, Player
from terraria_agent.models.task_queue import TaskPriority
from terraria_agent.orchestrator.agent_loop import AgentOrchestrator
from terraria_agent.spinal_cord.bt.core import Node, Status


class MockCapturer:
    def __init__(self, frame=None):
        self._frame = frame if frame is not None else np.zeros((10, 10, 3), dtype=np.uint8)
        self.calls = 0

    def capture(self):
        self.calls += 1
        return self._frame


class NoFrameCapturer:
    def capture(self):
        return None


class MockDetector:
    def __init__(self, state: GameState):
        self._state = state
        self.calls = 0

    def detect(self, frame):
        self.calls += 1
        return self._state


class MockKeyState:
    @property
    def held_keys(self):
        return frozenset(["a"])


class MockHand:
    def __init__(self):
        self.executed: list[list[GameAction]] = []
        self.released = 0
        self.key_state = MockKeyState()

    def execute(self, actions):
        self.executed.append(list(actions))

    def release_all(self):
        self.released += 1


class RecordingRoot(Node):
    def __init__(self, action_type=ActionType.MOVE, direction="right"):
        super().__init__("Root")
        self.ticks = 0
        self._action_type = action_type
        self._direction = direction

    def tick(self, ctx) -> Status:
        self.ticks += 1
        ctx.action_buffer.append(GameAction(action=self._action_type, direction=self._direction))
        ctx.bt_trace.append("Root>Combat")
        return Status.RUNNING


def _make_state(hp=100):
    return GameState(player=Player(hp=hp, max_hp=100, pos=(0.0, 0.0)))


class TestAgentOrchestrator:
    def test_tick_publishes_snapshot(self):
        bridge = StateBridge()
        orch = AgentOrchestrator(
            bridge,
            capture=MockCapturer(),
            detector=MockDetector(_make_state()),
            hand=MockHand(),
            bt_root=RecordingRoot(),
        )
        orch.tick_once()
        snap = bridge.get_snapshot()
        assert snap is not None
        assert snap.hp == 100
        assert snap.max_hp == 100
        assert snap.tick_count == 1
        assert snap.bt_status == "running"
        assert snap.active_bt_branch == "Root>Combat"
        assert "move right" in snap.action_buffer[0]

    def test_tick_runs_hand_execute(self):
        bridge = StateBridge()
        hand = MockHand()
        root = RecordingRoot()
        orch = AgentOrchestrator(
            bridge,
            capture=MockCapturer(),
            detector=MockDetector(_make_state()),
            hand=hand,
            bt_root=root,
        )
        orch.tick_once()
        assert len(hand.executed) == 1
        assert hand.executed[0][0].action == ActionType.MOVE

    def test_paused_skips_detection(self):
        bridge = StateBridge()
        bridge.set_paused(True)
        detector = MockDetector(_make_state())
        orch = AgentOrchestrator(
            bridge,
            capture=MockCapturer(),
            detector=detector,
            hand=MockHand(),
            bt_root=RecordingRoot(),
        )
        orch.tick_once()
        assert detector.calls == 0
        snap = bridge.get_snapshot()
        assert snap.bt_status == "paused"

    def test_command_goal(self):
        bridge = StateBridge()
        orch = AgentOrchestrator(
            bridge,
            capture=MockCapturer(),
            detector=MockDetector(_make_state()),
            hand=MockHand(),
            bt_root=RecordingRoot(),
        )
        bridge.send_command("goal: defeat wall of flesh")
        orch.tick_once()
        snap = bridge.get_snapshot()
        assert snap.current_goal == "defeat wall of flesh"

    def test_command_task_with_priority(self):
        bridge = StateBridge()
        orch = AgentOrchestrator(
            bridge,
            capture=MockCapturer(),
            detector=MockDetector(_make_state()),
            hand=MockHand(),
            bt_root=RecordingRoot(),
        )
        bridge.send_command("task: tree_nearby chop high")
        orch.tick_once()
        assert len(orch._task_queue.task_queue) == 1
        assert orch._task_queue.task_queue[0].priority == TaskPriority.HIGH

    def test_command_pause_resume(self):
        bridge = StateBridge()
        orch = AgentOrchestrator(
            bridge,
            capture=MockCapturer(),
            detector=MockDetector(_make_state()),
            hand=MockHand(),
            bt_root=RecordingRoot(),
        )
        bridge.send_command("pause")
        orch.tick_once()
        assert bridge.is_paused()
        bridge.send_command("resume")
        orch.tick_once()
        assert not bridge.is_paused()

    def test_command_clear(self):
        bridge = StateBridge()
        orch = AgentOrchestrator(
            bridge,
            capture=MockCapturer(),
            detector=MockDetector(_make_state()),
            hand=MockHand(),
            bt_root=RecordingRoot(),
        )
        bridge.send_command("task: t a low")
        orch.tick_once()
        assert len(orch._task_queue.task_queue) == 1
        bridge.send_command("clear")
        orch.tick_once()
        assert len(orch._task_queue.task_queue) == 0

    def test_stop_releases_keys(self):
        bridge = StateBridge()
        hand = MockHand()
        orch = AgentOrchestrator(
            bridge,
            capture=MockCapturer(),
            detector=MockDetector(_make_state()),
            hand=hand,
            bt_root=RecordingRoot(),
        )
        orch.stop()
        assert hand.released == 1
