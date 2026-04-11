from terraria_agent.spinal_cord.bt import Parallel, PrioritySelector, Sequence
from terraria_agent.spinal_cord.bt.leaves import Action
from terraria_agent.spinal_cord.bt.core import Node, Status
from terraria_agent.spinal_cord.trees.survival_tree import build_survival_tree, build_low_health_tree
from terraria_agent.spinal_cord.trees.combat_tree import build_threat_response_tree, build_combat_tree
from terraria_agent.spinal_cord.trees.exploration_tree import build_terrain_tree
from terraria_agent.spinal_cord.trees.task_executor import build_task_executor
from terraria_agent.models.actions import GameAction, ActionType


class Idle(Action):
    def execute(self, ctx):
        ctx.action_buffer.append(GameAction(action=ActionType.NONE))
        return Status.SUCCESS


class AlwaysSucceed(Node):
    """Wraps a child; always returns SUCCESS so Parallel peers keep running."""

    def __init__(self, child: Node, name: str = ""):
        super().__init__(name or f"Always({child.name})")
        self.child = child

    def tick(self, ctx) -> Status:
        self.child.tick(ctx)
        return Status.SUCCESS

    def reset(self) -> None:
        self.child.reset()


def build_root_tree():
    """
    ROOT [PrioritySelector]
    ├── SURVIVAL        — hp < 20% (pre-empts everything)
    ├── LOW_HEALTH      — hp < 50% (pre-empts everything)
    ├── THREAT_RESPONSE — urgent projectile dodge
    └── ACTIVE [Parallel] — combat + movement run together
        ├── Always(COMBAT)   — attack enemies without stopping movement
        └── MOVE_OR_EXPLORE [PrioritySelector]
            ├── TERRAIN         — pit / block wall / dark
            ├── TASK_EXECUTOR   — Brain's task queue
            └── IDLE            — fallback
    """
    move_branch = PrioritySelector(
        children=[
            build_terrain_tree(),
            build_task_executor(),
            Idle(name="Idle"),
        ],
        name="MoveOrExplore",
    )
    active = Parallel(
        children=[
            AlwaysSucceed(build_combat_tree(), name="CombatBG"),
            move_branch,
        ],
        success_threshold=2,
        name="Active",
    )
    return PrioritySelector(
        children=[
            build_survival_tree(),
            build_low_health_tree(),
            build_threat_response_tree(),
            active,
        ],
        name="Root",
    )
