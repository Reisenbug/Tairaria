from terraria_agent.models.game_state import Camera, GameState, InventorySlot, Player, WorldObject
from terraria_agent.models.actions import ActionType
from terraria_agent.models.task_queue import TaskQueue, Task, TaskPriority
from terraria_agent.spinal_cord.bt.core import Status
from terraria_agent.spinal_cord.actions.movement import MoveLeft, MoveRight, Jump, PlacePlatform, MoveToObject, MineForward
from terraria_agent.spinal_cord.context import TickContext

TQ = TaskQueue(goal="test", task_queue=[Task(trigger="default", action="idle", priority=TaskPriority.BASELINE)])


def _ctx(inventory=None, objects=None, player_pos=(0, 0)):
    return TickContext(
        game_state=GameState(
            player=Player(hp=400, max_hp=400, pos=player_pos),
            inventory=inventory or {},
            objects=objects or [],
        ),
        task_queue=TQ,
    )


class TestBasicMovement:
    def test_move_left(self):
        ctx = _ctx()
        assert MoveLeft().tick(ctx) == Status.SUCCESS
        assert ctx.action_buffer[0].action == ActionType.MOVE
        assert ctx.action_buffer[0].direction == "left"

    def test_move_right(self):
        ctx = _ctx()
        assert MoveRight().tick(ctx) == Status.SUCCESS
        assert ctx.action_buffer[0].direction == "right"

    def test_jump(self):
        ctx = _ctx()
        assert Jump().tick(ctx) == Status.SUCCESS
        assert ctx.action_buffer[0].action == ActionType.JUMP


class TestPlacePlatform:
    def test_with_platforms(self):
        ctx = _ctx(inventory={"platform": 5})
        assert PlacePlatform().tick(ctx) == Status.SUCCESS
        assert ctx.action_buffer[0].action == ActionType.PLACE_BLOCK

    def test_without_platforms(self):
        ctx = _ctx()
        assert PlacePlatform().tick(ctx) == Status.FAILURE


def _pickaxe_slot(idx: int) -> InventorySlot:
    return InventorySlot(slot_index=idx, id=1, name="copper_pickaxe", stack=1, pick=35)


class TestMineForward:
    def test_no_pickaxe_fails(self):
        ctx = _ctx()
        assert MineForward().tick(ctx) == Status.FAILURE

    def test_switches_to_pickaxe_and_attacks_right(self):
        slots = [InventorySlot(slot_index=i) for i in range(58)]
        slots[2] = _pickaxe_slot(2)
        ctx = TickContext(
            game_state=GameState(
                player=Player(hp=400, max_hp=400, pos=(0, 0), width=20, height=42, direction="right", selected_slot=0),
                camera=Camera(screen_pos=(0, 0), screen_size=(1920, 1080), zoom=1.0),
                inventory_slots=slots,
            ),
            task_queue=TQ,
        )
        assert MineForward().tick(ctx) == Status.SUCCESS
        kinds = [a.action for a in ctx.action_buffer]
        assert ActionType.SWITCH_SLOT in kinds
        assert ActionType.ATTACK in kinds
        switch = next(a for a in ctx.action_buffer if a.action == ActionType.SWITCH_SLOT)
        assert switch.slot == 2

    def test_already_selected_pickaxe_skips_switch(self):
        slots = [InventorySlot(slot_index=i) for i in range(58)]
        slots[0] = _pickaxe_slot(0)
        ctx = TickContext(
            game_state=GameState(
                player=Player(hp=400, max_hp=400, pos=(0, 0), width=20, height=42, direction="left", selected_slot=0),
                camera=Camera(screen_pos=(0, 0), screen_size=(1920, 1080), zoom=1.0),
                inventory_slots=slots,
            ),
            task_queue=TQ,
        )
        assert MineForward().tick(ctx) == Status.SUCCESS
        kinds = [a.action for a in ctx.action_buffer]
        assert ActionType.SWITCH_SLOT not in kinds
        assert ActionType.ATTACK in kinds


class TestMoveToObject:
    def test_object_to_the_right(self):
        ctx = _ctx(player_pos=(100, 0), objects=[WorldObject(type="tree", pos=(200, 0), distance=100)])
        assert MoveToObject("tree").tick(ctx) == Status.RUNNING
        assert ctx.action_buffer[0].direction == "right"

    def test_object_to_the_left(self):
        ctx = _ctx(player_pos=(200, 0), objects=[WorldObject(type="tree", pos=(100, 0), distance=100)])
        assert MoveToObject("tree").tick(ctx) == Status.RUNNING
        assert ctx.action_buffer[0].direction == "left"

    def test_already_at_object(self):
        ctx = _ctx(player_pos=(100, 0), objects=[WorldObject(type="tree", pos=(105, 0), distance=5)])
        assert MoveToObject("tree").tick(ctx) == Status.SUCCESS

    def test_no_object(self):
        ctx = _ctx()
        assert MoveToObject("tree").tick(ctx) == Status.FAILURE
