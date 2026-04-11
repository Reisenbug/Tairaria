from terraria_agent.models.game_state import GameState, Player, WorldObject
from terraria_agent.models.actions import ActionType
from terraria_agent.models.task_queue import TaskQueue, Task, TaskPriority
from terraria_agent.spinal_cord.bt.core import Status
from terraria_agent.spinal_cord.actions.interaction import ChopTree, PickUpValuableDrop, OpenChest
from terraria_agent.spinal_cord.context import TickContext

TQ = TaskQueue(goal="test", task_queue=[Task(trigger="default", action="idle", priority=TaskPriority.BASELINE)])


def _ctx(objects=None, hotbar=None, player_pos=(0, 0)):
    return TickContext(
        game_state=GameState(
            player=Player(hp=400, max_hp=400, pos=player_pos),
            objects=objects or [],
            hotbar=hotbar or [None] * 10,
        ),
        task_queue=TQ,
    )


class TestChopTree:
    def test_switches_to_axe_and_attacks(self):
        ctx = _ctx(
            objects=[WorldObject(type="tree", pos=(100, 0), distance=100)],
            hotbar=["sword", "axe", None, None, None, None, None, None, None, None],
        )
        assert ChopTree().tick(ctx) == Status.SUCCESS
        actions = [a.action for a in ctx.action_buffer]
        assert ActionType.SWITCH_SLOT in actions
        assert ActionType.ATTACK in actions

    def test_no_tree(self):
        assert ChopTree().tick(_ctx()) == Status.FAILURE


class TestPickUpValuableDrop:
    def test_picks_up_fruit(self):
        ctx = _ctx(
            objects=[WorldObject(type="fruit", pos=(50, 0), distance=50)],
            player_pos=(0, 0),
        )
        assert PickUpValuableDrop().tick(ctx) == Status.RUNNING
        assert ctx.action_buffer[0].direction == "right"

    def test_picks_up_gold_coin(self):
        ctx = _ctx(objects=[WorldObject(type="gold_coin", pos=(5, 0), distance=5)])
        assert PickUpValuableDrop().tick(ctx) == Status.SUCCESS

    def test_ignores_silver_coin(self):
        ctx = _ctx(objects=[WorldObject(type="silver_coin", pos=(5, 0), distance=5)])
        assert PickUpValuableDrop().tick(ctx) == Status.FAILURE

    def test_no_drops(self):
        assert PickUpValuableDrop().tick(_ctx()) == Status.FAILURE


class TestOpenChest:
    def test_opens_nearest(self):
        ctx = _ctx(objects=[WorldObject(type="chest", pos=(50, 0), distance=50)])
        assert OpenChest().tick(ctx) == Status.SUCCESS
        assert ctx.action_buffer[0].action == ActionType.INTERACT

    def test_no_chest(self):
        assert OpenChest().tick(_ctx()) == Status.FAILURE

    def test_smart_cursor_targets_between_player_and_chest(self):
        ctx = _ctx(
            objects=[WorldObject(type="chest", pos=(100, 0), distance=100)],
            player_pos=(0, 0),
        )
        ctx.smart_cursor = True
        assert OpenChest().tick(ctx) == Status.SUCCESS
        action = ctx.action_buffer[0]
        assert action.action == ActionType.INTERACT
        # midpoint target (world 50 vs chest 100 in plain ctx without camera offset)
        assert action.target is not None

    def test_smart_cursor_off_targets_chest_position(self):
        ctx = _ctx(
            objects=[WorldObject(type="chest", pos=(100, 0), distance=100)],
            player_pos=(0, 0),
        )
        assert ctx.smart_cursor is False
        assert OpenChest().tick(ctx) == Status.SUCCESS
        assert ctx.action_buffer[0].target is not None
