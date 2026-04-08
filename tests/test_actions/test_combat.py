from terraria_agent.models.game_state import GameState, Player, Enemy, Threat
from terraria_agent.models.actions import ActionType
from terraria_agent.models.task_queue import TaskQueue, Task, TaskPriority
from terraria_agent.spinal_cord.bt.core import Status
from terraria_agent.spinal_cord.actions.combat import AttackNearest, SwitchToSword, SwitchToBestWeapon, Dodge
from terraria_agent.spinal_cord.context import TickContext

TQ = TaskQueue(goal="test", task_queue=[Task(trigger="default", action="idle", priority=TaskPriority.BASELINE)])


def _ctx(enemies=None, threats=None, hotbar=None):
    return TickContext(
        game_state=GameState(
            player=Player(hp=400, max_hp=400, pos=(0, 0)),
            enemies=enemies or [],
            threats=threats or [],
            hotbar=hotbar or [None] * 10,
        ),
        task_queue=TQ,
    )


class TestAttackNearest:
    def test_attacks_closest(self):
        ctx = _ctx(enemies=[
            Enemy(type="far", pos=(500, 0), distance=500),
            Enemy(type="close", pos=(100, 0), distance=100),
        ])
        assert AttackNearest().tick(ctx) == Status.SUCCESS
        assert ctx.action_buffer[0].target is not None

    def test_no_enemies(self):
        assert AttackNearest().tick(_ctx()) == Status.FAILURE


class TestSwitchToSword:
    def test_finds_sword(self):
        ctx = _ctx(hotbar=["pickaxe", "iron_sword", None, None, None, None, None, None, None, None])
        assert SwitchToSword().tick(ctx) == Status.SUCCESS
        assert ctx.action_buffer[0].slot == 1

    def test_no_sword(self):
        ctx = _ctx(hotbar=["pickaxe", None, None, None, None, None, None, None, None, None])
        assert SwitchToSword().tick(ctx) == Status.FAILURE


class TestDodge:
    def test_dodge_away_from_threat(self):
        ctx = _ctx(threats=[Threat(type="proj", pos=(50, 0), direction="left", urgent=True)])
        assert Dodge().tick(ctx) == Status.SUCCESS
        assert ctx.action_buffer[0].direction == "right"
        assert ctx.action_buffer[1].action == ActionType.JUMP

    def test_no_threats(self):
        assert Dodge().tick(_ctx()) == Status.FAILURE
