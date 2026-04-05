import pytest

from terraria_agent.models.game_state import GameState, Player
from terraria_agent.models.task_queue import TaskQueue, Task, TaskPriority
from terraria_agent.spinal_cord.context import TickContext


@pytest.fixture
def default_player():
    return Player(hp=400, max_hp=400, pos=(600.0, 300.0))


@pytest.fixture
def default_task_queue():
    return TaskQueue(
        goal="前往丛林",
        task_queue=[
            Task(trigger="default", action="向左移动", priority=TaskPriority.BASELINE),
        ],
    )


@pytest.fixture
def default_state(default_player):
    return GameState(player=default_player)


@pytest.fixture
def make_ctx(default_task_queue):
    def _make(state: GameState, task_queue: TaskQueue | None = None) -> TickContext:
        return TickContext(game_state=state, task_queue=task_queue or default_task_queue)
    return _make
