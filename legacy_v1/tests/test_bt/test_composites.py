import pytest

from terraria_agent.models.game_state import GameState, Player
from terraria_agent.models.task_queue import TaskQueue, Task, TaskPriority
from terraria_agent.spinal_cord.bt.core import Status, Node
from terraria_agent.spinal_cord.bt.composites import (
    Sequence, Selector, PrioritySelector, Parallel, DynamicSelector,
)
from terraria_agent.spinal_cord.context import TickContext


class SuccessNode(Node):
    def tick(self, ctx): return Status.SUCCESS

class FailureNode(Node):
    def tick(self, ctx): return Status.FAILURE

class RunningNode(Node):
    def tick(self, ctx): return Status.RUNNING

class CountNode(Node):
    def __init__(self, results: list[Status], name=""):
        super().__init__(name)
        self.results = results
        self.call_count = 0

    def tick(self, ctx):
        idx = min(self.call_count, len(self.results) - 1)
        self.call_count += 1
        return self.results[idx]

    def reset(self):
        self.call_count = 0


class TrackResetNode(Node):
    def __init__(self, status=Status.RUNNING, name=""):
        super().__init__(name)
        self._status = status
        self.reset_count = 0

    def tick(self, ctx):
        return self._status

    def reset(self):
        self.reset_count += 1


@pytest.fixture
def ctx():
    state = GameState(player=Player(hp=400, max_hp=400, pos=(0, 0)))
    tq = TaskQueue(goal="test", task_queue=[Task(trigger="default", action="idle", priority=TaskPriority.BASELINE)])
    return TickContext(game_state=state, task_queue=tq)


# --- Sequence ---

class TestSequence:
    def test_all_success(self, ctx):
        seq = Sequence([SuccessNode(), SuccessNode(), SuccessNode()])
        assert seq.tick(ctx) == Status.SUCCESS

    def test_first_failure(self, ctx):
        seq = Sequence([FailureNode(), SuccessNode()])
        assert seq.tick(ctx) == Status.FAILURE

    def test_middle_failure(self, ctx):
        seq = Sequence([SuccessNode(), FailureNode(), SuccessNode()])
        assert seq.tick(ctx) == Status.FAILURE

    def test_running_resumes(self, ctx):
        c = CountNode([Status.RUNNING, Status.SUCCESS])
        seq = Sequence([SuccessNode(), c, SuccessNode()])
        assert seq.tick(ctx) == Status.RUNNING
        assert seq.tick(ctx) == Status.SUCCESS
        assert c.call_count == 2

    def test_reset(self, ctx):
        c = CountNode([Status.RUNNING, Status.SUCCESS])
        seq = Sequence([c])
        seq.tick(ctx)
        seq.reset()
        assert seq._running_idx == 0
        assert c.call_count == 0


# --- Selector ---

class TestSelector:
    def test_first_success(self, ctx):
        sel = Selector([SuccessNode(), FailureNode()])
        assert sel.tick(ctx) == Status.SUCCESS

    def test_all_failure(self, ctx):
        sel = Selector([FailureNode(), FailureNode()])
        assert sel.tick(ctx) == Status.FAILURE

    def test_fallback_to_second(self, ctx):
        sel = Selector([FailureNode(), SuccessNode()])
        assert sel.tick(ctx) == Status.SUCCESS

    def test_running_resumes(self, ctx):
        c = CountNode([Status.RUNNING, Status.SUCCESS])
        sel = Selector([FailureNode(), c])
        assert sel.tick(ctx) == Status.RUNNING
        assert sel.tick(ctx) == Status.SUCCESS


# --- PrioritySelector ---

class TestPrioritySelector:
    def test_high_priority_wins(self, ctx):
        ps = PrioritySelector([SuccessNode(), FailureNode()])
        assert ps.tick(ctx) == Status.SUCCESS

    def test_fallback(self, ctx):
        ps = PrioritySelector([FailureNode(), SuccessNode()])
        assert ps.tick(ctx) == Status.SUCCESS

    def test_all_fail(self, ctx):
        ps = PrioritySelector([FailureNode(), FailureNode()])
        assert ps.tick(ctx) == Status.FAILURE

    def test_preemption_resets_lower(self, ctx):
        low = TrackResetNode(Status.RUNNING, name="low")
        high = CountNode([Status.FAILURE, Status.SUCCESS], name="high")
        ps = PrioritySelector([high, low])
        # tick 1: high fails, low is RUNNING
        assert ps.tick(ctx) == Status.RUNNING
        assert low.reset_count == 0
        # tick 2: high succeeds, low should be reset
        assert ps.tick(ctx) == Status.SUCCESS
        assert low.reset_count == 1


# --- Parallel ---

class TestParallel:
    def test_all_success(self, ctx):
        p = Parallel([SuccessNode(), SuccessNode()])
        assert p.tick(ctx) == Status.SUCCESS

    def test_partial_success_threshold(self, ctx):
        p = Parallel([SuccessNode(), FailureNode(), SuccessNode()], success_threshold=2)
        assert p.tick(ctx) == Status.SUCCESS

    def test_too_many_failures(self, ctx):
        p = Parallel([FailureNode(), FailureNode(), SuccessNode()], success_threshold=2)
        assert p.tick(ctx) == Status.FAILURE

    def test_running(self, ctx):
        p = Parallel([SuccessNode(), RunningNode()], success_threshold=2)
        assert p.tick(ctx) == Status.RUNNING


# --- DynamicSelector ---

class TestDynamicSelector:
    def test_basic_selection(self, ctx):
        children = [FailureNode(), SuccessNode()]
        ds = DynamicSelector(provider=lambda c: children)
        assert ds.tick(ctx) == Status.SUCCESS

    def test_empty_provider(self, ctx):
        ds = DynamicSelector(provider=lambda c: [])
        assert ds.tick(ctx) == Status.FAILURE

    def test_children_rebuild_resets_running(self, ctx):
        old_running = TrackResetNode(Status.RUNNING)
        children_v1 = [old_running]
        children_v2 = [SuccessNode()]

        versions = iter([children_v1, children_v2])
        ds = DynamicSelector(provider=lambda c: next(versions))

        assert ds.tick(ctx) == Status.RUNNING
        assert ds.tick(ctx) == Status.SUCCESS
        assert old_running.reset_count == 1
