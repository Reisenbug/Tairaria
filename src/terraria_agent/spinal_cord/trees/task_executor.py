from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from terraria_agent.spinal_cord.bt import DynamicSelector, Parallel, Sequence
from terraria_agent.spinal_cord.bt.core import Node
from terraria_agent.spinal_cord.bt.leaves import Condition
from terraria_agent.spinal_cord.actions.movement import MoveLeft, MoveRight, MoveToObject
from terraria_agent.spinal_cord.actions.interaction import (
    ShakeTree, ChopBigTree, BigTreeChopped, PickUpValuableDrop,
    OpenChest, EnsureSmartCursorOn, LootAll,
)
from terraria_agent.spinal_cord.actions.crafting import CraftPlatforms

if TYPE_CHECKING:
    from terraria_agent.spinal_cord.context import TickContext


class TriggerCondition(Condition):
    def __init__(self, predicate: Callable[[TickContext], bool], name: str = ""):
        super().__init__(name)
        self._predicate = predicate

    def check(self, ctx: TickContext) -> bool:
        return self._predicate(ctx)


def _has_big_tree_nearby(ctx: TickContext) -> bool:
    from terraria_agent.spinal_cord.actions.interaction import (
        _tree_height, _BIG_TREE_HEIGHT, _big_trees_chopped, _BIG_TREE_LIMIT,
    )
    if _big_trees_chopped >= _BIG_TREE_LIMIT:
        return False
    for o in ctx.game_state.objects:
        if o.type == "tree" and o.distance <= 6.0 and _tree_height(ctx, o) >= _BIG_TREE_HEIGHT:
            return True
    return False


TRIGGER_REGISTRY: dict[str, Callable[[TickContext], bool]] = {
    "big_tree_nearby": _has_big_tree_nearby,
    "chest_nearby": lambda ctx: any(o.type == "chest" for o in ctx.game_state.objects),
    "wood_gte_10": lambda ctx: ctx.game_state.inventory.get("wood", 0) >= 10,
    "default": lambda ctx: True,
}


def _build_task_subtree(trigger: str, action: str) -> Node | None:
    if trigger == "big_tree_nearby":
        return Sequence(
            children=[
                TriggerCondition(TRIGGER_REGISTRY["big_tree_nearby"], name="HasBigTree"),
                MoveToObject("tree", reach_tiles=4.0),
                ChopBigTree(),
                BigTreeChopped(),
                PickUpValuableDrop(),
            ],
            name="Task_chop_big_tree",
        )
    elif trigger == "chest_nearby":
        return Sequence(
            children=[
                TriggerCondition(TRIGGER_REGISTRY["chest_nearby"], name="HasChest"),
                MoveToObject("chest"),
                EnsureSmartCursorOn(),
                OpenChest(),
                LootAll(),
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
    elif trigger == "default" and action == "move_right":
        return Parallel(
            children=[MoveRight(name="WalkRight"), ShakeTree(name="ShakeTree")],
            success_threshold=2,
            name="Task_walk_shake",
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
