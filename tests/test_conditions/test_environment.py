from terraria_agent.models.game_state import GameState, Player, WorldObject, TerrainType
from terraria_agent.models.task_queue import TaskQueue, Task, TaskPriority
from terraria_agent.spinal_cord.bt.core import Status
from terraria_agent.spinal_cord.conditions.environment import (
    IsPitAhead, IsBlockWallAhead, IsDark, HasTreeNearby, HasChestNearby,
)
from terraria_agent.spinal_cord.context import TickContext

TQ = TaskQueue(goal="test", task_queue=[Task(trigger="default", action="idle", priority=TaskPriority.BASELINE)])


def _ctx(terrain=TerrainType.FLAT, is_dark=False, objects=None):
    return TickContext(
        game_state=GameState(
            player=Player(hp=400, max_hp=400, pos=(0, 0)),
            terrain_ahead=terrain,
            is_dark=is_dark,
            objects=objects or [],
        ),
        task_queue=TQ,
    )


class TestTerrain:
    def test_pit(self):
        assert IsPitAhead().tick(_ctx(TerrainType.PIT)) == Status.SUCCESS
        assert IsPitAhead().tick(_ctx(TerrainType.FLAT)) == Status.FAILURE

    def test_block_wall(self):
        assert IsBlockWallAhead().tick(_ctx(TerrainType.BLOCK_WALL)) == Status.SUCCESS
        assert IsBlockWallAhead().tick(_ctx(TerrainType.FLAT)) == Status.FAILURE

    def test_dark(self):
        assert IsDark().tick(_ctx(is_dark=True)) == Status.SUCCESS
        assert IsDark().tick(_ctx(is_dark=False)) == Status.FAILURE


class TestObjectNearby:
    def test_tree_nearby(self):
        assert HasTreeNearby().tick(_ctx(objects=[WorldObject(type="tree", pos=(100, 0), distance=100)])) == Status.SUCCESS

    def test_tree_too_far(self):
        assert HasTreeNearby(max_distance=50).tick(_ctx(objects=[WorldObject(type="tree", pos=(100, 0), distance=100)])) == Status.FAILURE

    def test_chest_nearby(self):
        assert HasChestNearby().tick(_ctx(objects=[WorldObject(type="chest", pos=(50, 0), distance=50)])) == Status.SUCCESS

    def test_no_chest(self):
        assert HasChestNearby().tick(_ctx()) == Status.FAILURE
