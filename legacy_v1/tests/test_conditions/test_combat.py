from terraria_agent.models.game_state import GameState, Player, Enemy, EnemyThreat, Threat
from terraria_agent.models.task_queue import TaskQueue, Task, TaskPriority
from terraria_agent.spinal_cord.bt.core import Status
from terraria_agent.spinal_cord.conditions.combat import (
    HasEnemiesNearby, IsSurrounded, EnemyIsWeak, EnemyIsMedium, EnemyIsDangerous, HasUrgentThreat,
)
from terraria_agent.spinal_cord.context import TickContext

TQ = TaskQueue(goal="test", task_queue=[Task(trigger="default", action="idle", priority=TaskPriority.BASELINE)])


def _ctx(enemies=None, threats=None):
    return TickContext(
        game_state=GameState(
            player=Player(hp=400, max_hp=400, pos=(0, 0)),
            enemies=enemies or [],
            threats=threats or [],
        ),
        task_queue=TQ,
    )


class TestHasEnemiesNearby:
    def test_no_enemies(self):
        assert HasEnemiesNearby().tick(_ctx()) == Status.FAILURE

    def test_far_enemy(self):
        assert HasEnemiesNearby(max_distance=100).tick(
            _ctx([Enemy(type="slime", pos=(500, 0), distance=500)])
        ) == Status.FAILURE

    def test_close_enemy(self):
        assert HasEnemiesNearby().tick(
            _ctx([Enemy(type="slime", pos=(100, 0), distance=100)])
        ) == Status.SUCCESS


class TestIsSurrounded:
    def test_not_enough(self):
        assert IsSurrounded(min_enemies=3).tick(
            _ctx([Enemy(type="a", pos=(0, 0), distance=50), Enemy(type="b", pos=(0, 0), distance=50)])
        ) == Status.FAILURE

    def test_surrounded(self):
        enemies = [Enemy(type=f"e{i}", pos=(0, 0), distance=50) for i in range(4)]
        assert IsSurrounded(min_enemies=3).tick(_ctx(enemies)) == Status.SUCCESS


class TestEnemyThreatLevels:
    def test_weak(self):
        assert EnemyIsWeak().tick(_ctx([Enemy(type="slime", pos=(0, 0), threat=EnemyThreat.WEAK)])) == Status.SUCCESS
        assert EnemyIsWeak().tick(_ctx([Enemy(type="bat", pos=(0, 0), threat=EnemyThreat.MEDIUM)])) == Status.FAILURE

    def test_medium(self):
        assert EnemyIsMedium().tick(_ctx([Enemy(type="bat", pos=(0, 0), threat=EnemyThreat.MEDIUM)])) == Status.SUCCESS

    def test_dangerous(self):
        assert EnemyIsDangerous().tick(_ctx([Enemy(type="demon", pos=(0, 0), threat=EnemyThreat.DANGEROUS)])) == Status.SUCCESS
        assert EnemyIsDangerous().tick(_ctx([Enemy(type="boss", pos=(0, 0), threat=EnemyThreat.BOSS)])) == Status.SUCCESS


class TestHasUrgentThreat:
    def test_no_threats(self):
        assert HasUrgentThreat().tick(_ctx()) == Status.FAILURE

    def test_non_urgent(self):
        assert HasUrgentThreat().tick(_ctx(threats=[Threat(type="proj", pos=(0, 0), urgent=False)])) == Status.FAILURE

    def test_urgent(self):
        assert HasUrgentThreat().tick(_ctx(threats=[Threat(type="proj", pos=(0, 0), urgent=True)])) == Status.SUCCESS
