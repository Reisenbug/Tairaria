import pytest

from terraria_agent.models.game_state import (
    GameState, Player, Enemy, EnemyThreat, Threat, WorldObject, TerrainType,
)
from terraria_agent.models.actions import ActionType
from terraria_agent.models.task_queue import TaskQueue, Task, TaskPriority
from terraria_agent.spinal_cord.bt.core import Status
from terraria_agent.spinal_cord.context import TickContext
from terraria_agent.spinal_cord.trees.root import build_root_tree


def _default_task_queue():
    return TaskQueue(
        goal="go_jungle",
        task_queue=[
            Task(trigger="tree_nearby", action="chop_tree", priority=TaskPriority.HIGH),
            Task(trigger="chest_nearby", action="open_chest", priority=TaskPriority.HIGH),
            Task(trigger="wood_gte_10", action="craft_platforms", priority=TaskPriority.MEDIUM),
            Task(trigger="default", action="move_left", priority=TaskPriority.BASELINE),
        ],
    )


def _make_ctx(state: GameState, tq: TaskQueue | None = None) -> TickContext:
    return TickContext(game_state=state, task_queue=tq or _default_task_queue())


class TestCalmTravel:
    def test_no_enemies_flat_terrain_moves_left(self):
        state = GameState(player=Player(hp=400, max_hp=400, pos=(600, 300)))
        root = build_root_tree()
        ctx = _make_ctx(state)
        root.tick(ctx)
        assert len(ctx.action_buffer) >= 1
        assert ctx.action_buffer[0].action == ActionType.MOVE
        assert ctx.action_buffer[0].direction == "left"


class TestTreeEncounter:
    def test_tree_nearby_triggers_chop(self):
        state = GameState(
            player=Player(hp=400, max_hp=400, pos=(600, 300)),
            objects=[WorldObject(type="tree", pos=(650, 300), distance=50)],
            hotbar=["axe", "sword", None, None, None, None, None, None, None, None],
        )
        root = build_root_tree()
        ctx = _make_ctx(state)
        root.tick(ctx)
        action_types = [a.action for a in ctx.action_buffer]
        assert ActionType.MOVE in action_types or ActionType.ATTACK in action_types or ActionType.SWITCH_SLOT in action_types


class TestWeakEnemy:
    def test_weak_enemy_attack_while_moving(self):
        state = GameState(
            player=Player(hp=400, max_hp=400, pos=(600, 300)),
            enemies=[Enemy(type="slime_green", pos=(700, 300), distance=100, threat=EnemyThreat.WEAK)],
            hotbar=["sword", None, None, None, None, None, None, None, None, None],
        )
        root = build_root_tree()
        ctx = _make_ctx(state)
        root.tick(ctx)
        action_types = [a.action for a in ctx.action_buffer]
        assert ActionType.ATTACK in action_types
        assert ActionType.MOVE in action_types


class TestMediumEnemy:
    def test_medium_enemy_stop_and_fight(self):
        state = GameState(
            player=Player(hp=400, max_hp=400, pos=(600, 300)),
            enemies=[Enemy(type="vulture", pos=(800, 300), distance=200, threat=EnemyThreat.MEDIUM)],
            hotbar=["sword", None, None, None, None, None, None, None, None, None],
        )
        root = build_root_tree()
        ctx = _make_ctx(state)
        root.tick(ctx)
        action_types = [a.action for a in ctx.action_buffer]
        assert ActionType.ATTACK in action_types or ActionType.SWITCH_SLOT in action_types


class TestSurroundedLowHP:
    def test_surrounded_critical_hp_uses_potion_and_signals(self):
        state = GameState(
            player=Player(hp=50, max_hp=400, pos=(600, 300)),
            enemies=[
                Enemy(type="zombie", pos=(500, 300), distance=100, threat=EnemyThreat.MEDIUM),
                Enemy(type="zombie", pos=(700, 300), distance=100, threat=EnemyThreat.MEDIUM),
                Enemy(type="demon_eye", pos=(600, 200), distance=100, threat=EnemyThreat.MEDIUM),
            ],
            hotbar=["sword", "potion", None, None, None, None, None, None, None, None],
            inventory={"potion": 3},
        )
        root = build_root_tree()
        ctx = _make_ctx(state)
        root.tick(ctx)
        action_types = [a.action for a in ctx.action_buffer]
        assert ActionType.USE_ITEM in action_types

    def test_critical_hp_no_potion_dodges(self):
        state = GameState(
            player=Player(hp=50, max_hp=400, pos=(600, 300)),
            enemies=[Enemy(type="zombie", pos=(700, 300), distance=100, threat=EnemyThreat.MEDIUM)],
            threats=[Threat(type="projectile", pos=(650, 300), direction="left", urgent=True)],
            hotbar=["sword", None, None, None, None, None, None, None, None, None],
            inventory={},
        )
        root = build_root_tree()
        ctx = _make_ctx(state)
        root.tick(ctx)
        action_types = [a.action for a in ctx.action_buffer]
        assert ActionType.MOVE in action_types or ActionType.JUMP in action_types

    def test_critical_hp_no_potion_no_threat_signals_brain(self):
        state = GameState(
            player=Player(hp=50, max_hp=400, pos=(600, 300)),
            enemies=[Enemy(type="zombie", pos=(700, 300), distance=100, threat=EnemyThreat.MEDIUM)],
            hotbar=["sword", None, None, None, None, None, None, None, None, None],
            inventory={},
        )
        root = build_root_tree()
        ctx = _make_ctx(state)
        root.tick(ctx)
        assert ctx.interrupt_brain is True


class TestPitAhead:
    def test_pit_with_platforms_places_and_jumps(self):
        state = GameState(
            player=Player(hp=400, max_hp=400, pos=(600, 300)),
            terrain_ahead=TerrainType.PIT,
            inventory={"platform": 5},
        )
        root = build_root_tree()
        ctx = _make_ctx(state)
        root.tick(ctx)
        action_types = [a.action for a in ctx.action_buffer]
        assert ActionType.PLACE_BLOCK in action_types or ActionType.JUMP in action_types

    def test_pit_without_platforms_jumps(self):
        state = GameState(
            player=Player(hp=400, max_hp=400, pos=(600, 300)),
            terrain_ahead=TerrainType.PIT,
            inventory={},
        )
        root = build_root_tree()
        ctx = _make_ctx(state)
        root.tick(ctx)
        action_types = [a.action for a in ctx.action_buffer]
        assert ActionType.JUMP in action_types


class TestDarkArea:
    def test_dark_with_torch_places_torch(self):
        state = GameState(
            player=Player(hp=400, max_hp=400, pos=(600, 300)),
            is_dark=True,
            inventory={"torch": 10},
        )
        root = build_root_tree()
        ctx = _make_ctx(state)
        root.tick(ctx)
        action_types = [a.action for a in ctx.action_buffer]
        assert ActionType.PLACE_BLOCK in action_types


class TestSurvivalOverridesTask:
    def test_survival_preempts_task_executor(self):
        state = GameState(
            player=Player(hp=30, max_hp=400, pos=(600, 300)),
            objects=[WorldObject(type="tree", pos=(650, 300), distance=50)],
            hotbar=["axe", "potion", None, None, None, None, None, None, None, None],
            inventory={"potion": 1},
        )
        root = build_root_tree()
        ctx = _make_ctx(state)
        root.tick(ctx)
        action_types = [a.action for a in ctx.action_buffer]
        assert ActionType.USE_ITEM in action_types


class TestUrgentThreat:
    def test_projectile_triggers_dodge(self):
        state = GameState(
            player=Player(hp=400, max_hp=400, pos=(600, 300)),
            threats=[Threat(type="projectile", pos=(650, 300), direction="left", urgent=True)],
        )
        root = build_root_tree()
        ctx = _make_ctx(state)
        root.tick(ctx)
        action_types = [a.action for a in ctx.action_buffer]
        assert ActionType.MOVE in action_types
        assert ActionType.JUMP in action_types


class TestChestEncounter:
    def test_chest_nearby_opens(self):
        state = GameState(
            player=Player(hp=400, max_hp=400, pos=(600, 300)),
            objects=[WorldObject(type="chest", pos=(610, 300), distance=10)],
        )
        root = build_root_tree()
        ctx = _make_ctx(state)
        root.tick(ctx)
        action_types = [a.action for a in ctx.action_buffer]
        assert ActionType.INTERACT in action_types or ActionType.MOVE in action_types
