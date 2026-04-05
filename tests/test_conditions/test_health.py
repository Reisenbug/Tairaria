from terraria_agent.models.game_state import GameState, Player
from terraria_agent.models.task_queue import TaskQueue, Task, TaskPriority
from terraria_agent.spinal_cord.bt.core import Status
from terraria_agent.spinal_cord.conditions.health import IsHealthCritical, IsHealthLow
from terraria_agent.spinal_cord.context import TickContext

TQ = TaskQueue(goal="test", task_queue=[Task(trigger="default", action="idle", priority=TaskPriority.BASELINE)])


def _ctx(hp, max_hp=400):
    return TickContext(game_state=GameState(player=Player(hp=hp, max_hp=max_hp, pos=(0, 0))), task_queue=TQ)


class TestIsHealthCritical:
    def test_below_threshold(self):
        assert IsHealthCritical(0.2).tick(_ctx(70)) == Status.SUCCESS  # 17.5%

    def test_above_threshold(self):
        assert IsHealthCritical(0.2).tick(_ctx(100)) == Status.FAILURE  # 25%

    def test_custom_threshold(self):
        assert IsHealthCritical(0.5).tick(_ctx(190)) == Status.SUCCESS  # 47.5%


class TestIsHealthLow:
    def test_below_threshold(self):
        assert IsHealthLow(0.5).tick(_ctx(190)) == Status.SUCCESS

    def test_above_threshold(self):
        assert IsHealthLow(0.5).tick(_ctx(300)) == Status.FAILURE
