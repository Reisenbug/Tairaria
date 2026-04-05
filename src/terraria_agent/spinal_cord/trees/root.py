from terraria_agent.spinal_cord.bt import PrioritySelector
from terraria_agent.spinal_cord.bt.leaves import Action
from terraria_agent.spinal_cord.bt.core import Status
from terraria_agent.spinal_cord.trees.survival_tree import build_survival_tree, build_low_health_tree
from terraria_agent.spinal_cord.trees.combat_tree import build_threat_response_tree, build_combat_tree
from terraria_agent.spinal_cord.trees.exploration_tree import build_terrain_tree
from terraria_agent.spinal_cord.trees.task_executor import build_task_executor
from terraria_agent.models.actions import GameAction, ActionType


class Idle(Action):
    def execute(self, ctx):
        ctx.action_buffer.append(GameAction(action=ActionType.NONE))
        return Status.SUCCESS


def build_root_tree():
    """
    ROOT [PrioritySelector] — re-evaluates from top each tick
    ├── SURVIVAL        — hp < 20%
    ├── THREAT_RESPONSE — urgent projectile
    ├── COMBAT          — dangerous > medium > weak
    ├── LOW_HEALTH      — hp < 50%
    ├── TERRAIN         — pit / block wall / dark
    ├── TASK_EXECUTOR   — Brain's task queue
    └── IDLE            — fallback
    """
    return PrioritySelector(
        children=[
            build_survival_tree(),
            build_threat_response_tree(),
            build_combat_tree(),
            build_low_health_tree(),
            build_terrain_tree(),
            build_task_executor(),
            Idle(name="Idle"),
        ],
        name="Root",
    )
