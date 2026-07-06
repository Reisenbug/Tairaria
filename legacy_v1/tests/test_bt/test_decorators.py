import pytest

from terraria_agent.models.game_state import GameState, Player
from terraria_agent.models.task_queue import TaskQueue, Task, TaskPriority
from terraria_agent.spinal_cord.bt.core import Status, Node
from terraria_agent.spinal_cord.bt.decorators import Inverter, RepeatUntilFail, Cooldown, ForceSuccess
from terraria_agent.spinal_cord.context import TickContext


class SuccessNode(Node):
    def tick(self, ctx): return Status.SUCCESS

class FailureNode(Node):
    def tick(self, ctx): return Status.FAILURE

class RunningNode(Node):
    def tick(self, ctx): return Status.RUNNING


@pytest.fixture
def ctx():
    state = GameState(player=Player(hp=400, max_hp=400, pos=(0, 0)))
    tq = TaskQueue(goal="test", task_queue=[Task(trigger="default", action="idle", priority=TaskPriority.BASELINE)])
    return TickContext(game_state=state, task_queue=tq)


class TestInverter:
    def test_inverts_success(self, ctx):
        assert Inverter(SuccessNode()).tick(ctx) == Status.FAILURE

    def test_inverts_failure(self, ctx):
        assert Inverter(FailureNode()).tick(ctx) == Status.SUCCESS

    def test_passes_running(self, ctx):
        assert Inverter(RunningNode()).tick(ctx) == Status.RUNNING


class TestRepeatUntilFail:
    def test_success_returns_running(self, ctx):
        assert RepeatUntilFail(SuccessNode()).tick(ctx) == Status.RUNNING

    def test_failure_returns_success(self, ctx):
        assert RepeatUntilFail(FailureNode()).tick(ctx) == Status.SUCCESS

    def test_running_returns_running(self, ctx):
        assert RepeatUntilFail(RunningNode()).tick(ctx) == Status.RUNNING


class TestCooldown:
    def test_first_call_passes_through(self, ctx):
        cd = Cooldown(SuccessNode(), duration=1.0)
        assert cd.tick(ctx) == Status.SUCCESS

    def test_blocks_during_cooldown(self, ctx):
        t = 0.0
        cd = Cooldown(SuccessNode(), duration=1.0, clock=lambda: t)
        assert cd.tick(ctx) == Status.SUCCESS
        assert cd.tick(ctx) == Status.FAILURE  # still within 1.0s

    def test_allows_after_cooldown(self, ctx):
        times = iter([0.0, 0.0, 2.0, 2.0])
        cd = Cooldown(SuccessNode(), duration=1.0, clock=lambda: next(times))
        assert cd.tick(ctx) == Status.SUCCESS
        assert cd.tick(ctx) == Status.FAILURE
        assert cd.tick(ctx) == Status.SUCCESS

    def test_reset_clears_cooldown(self, ctx):
        t = 0.0
        cd = Cooldown(SuccessNode(), duration=10.0, clock=lambda: t)
        cd.tick(ctx)
        cd.reset()
        assert cd.tick(ctx) == Status.SUCCESS


class TestForceSuccess:
    def test_failure_becomes_success(self, ctx):
        assert ForceSuccess(FailureNode()).tick(ctx) == Status.SUCCESS

    def test_success_stays(self, ctx):
        assert ForceSuccess(SuccessNode()).tick(ctx) == Status.SUCCESS

    def test_running_stays(self, ctx):
        assert ForceSuccess(RunningNode()).tick(ctx) == Status.RUNNING
