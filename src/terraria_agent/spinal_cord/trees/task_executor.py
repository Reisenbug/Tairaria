from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from terraria_agent.spinal_cord.bt import DynamicSelector, Sequence
from terraria_agent.spinal_cord.bt.core import Node
from terraria_agent.spinal_cord.bt.leaves import Condition
from terraria_agent.spinal_cord.actions.movement import MoveLeft, MoveToObject
from terraria_agent.spinal_cord.actions.interaction import ChopTree, PickUpValuableDrop, OpenChest
from terraria_agent.spinal_cord.actions.crafting import CraftPlatforms

if TYPE_CHECKING:
    from terraria_agent.spinal_cord.context import TickContext


class TriggerCondition(Condition):
    def __init__(self, predicate: Callable[[TickContext], bool], name: str = ""):
        super().__init__(name)
        self._predicate = predicate

    def check(self, ctx: TickContext) -> bool:
        return self._predicate(ctx)


TRIGGER_REGISTRY: dict[str, Callable[[TickContext], bool]] = {
    "tree_nearby": lambda ctx: any(o.type == "tree" for o in ctx.game_state.objects),
    "chest_nearby": lambda ctx: any(o.type == "chest" for o in ctx.game_state.objects),
    "wood_gte_10": lambda ctx: ctx.game_state.inventory.get("wood", 0) >= 10,
    "default": lambda ctx: True,
}


def _build_task_subtree(trigger: str, action: str) -> Node | None:
    if trigger == "tree_nearby":
        return Sequence(
            children=[
                TriggerCondition(TRIGGER_REGISTRY["tree_nearby"], name="HasTree"),
                MoveToObject("tree"),
                ChopTree(),
                PickUpValuableDrop(),
            ],
            name="Task_tree_nearby",
        )
    elif trigger == "chest_nearby":
        return Sequence(
            children=[
                TriggerCondition(TRIGGER_REGISTRY["chest_nearby"], name="HasChest"),
                MoveToObject("chest"),
                OpenChest(),
            ],
            name="Task_chest_nearby",
        )
    elif trigger == "wood_gte_10":
        return Sequence(
            children=[
                TriggerCondition(TRIGGER_REGISTRY["wood_gte_10"], name="EnoughWood"),
                CraftPlatforms(),
            ],
            name="Task_craft_platforms",
        )
    elif trigger == "default":
        return MoveLeft(name="Task_default_move_left")
    return None


def _provide_task_nodes(ctx: TickContext) -> list[Node]:
    priority_order = ["critical", "high", "medium", "low", "baseline"]
    sorted_tasks = sorted(
        ctx.task_queue.task_queue,
        key=lambda t: priority_order.index(t.priority.value),
    )
    nodes = []
    for task in sorted_tasks:
        node = _build_task_subtree(task.trigger, task.action)
        if node:
            nodes.append(node)
    return nodes


def build_task_executor():
    return DynamicSelector(provider=_provide_task_nodes, name="TaskExecutor")
