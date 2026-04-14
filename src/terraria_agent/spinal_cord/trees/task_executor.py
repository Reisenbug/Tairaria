from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Callable

from terraria_agent.spinal_cord.bt import Parallel, Sequence
from terraria_agent.spinal_cord.bt.core import Node, Status
from terraria_agent.spinal_cord.bt.leaves import Condition
from terraria_agent.spinal_cord.actions.movement import MoveLeft, MoveRight, MoveToObject, BuildBridge
from terraria_agent.spinal_cord.actions.interaction import (
    ShakeTree, ChopBigTree, BigTreeChopped, PickUpValuableDrop,
    OpenChest, EnsureSmartCursorOn, LootAll,
)
from terraria_agent.spinal_cord.actions.crafting import CraftPlatforms

if TYPE_CHECKING:
    from terraria_agent.spinal_cord.context import TickContext


class TaskMode(str, Enum):
    EXCLUSIVE = "exclusive"
    CONCURRENT = "concurrent"


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


def _pit_unreachable_ahead(ctx: TickContext) -> bool:
    from terraria_agent.models.game_state import TerrainType
    return ctx.game_state.terrain_ahead == TerrainType.PIT


TRIGGER_REGISTRY: dict[str, Callable[[TickContext], bool]] = {
    "big_tree_nearby": _has_big_tree_nearby,
    "chest_nearby": lambda ctx: any(o.type == "chest" for o in ctx.game_state.objects),
    "wood_gte_10": lambda ctx: ctx.game_state.inventory.get("wood", 0) >= 10,
    "pit_unreachable_ahead": _pit_unreachable_ahead,
    "default": lambda ctx: True,
}


TASK_MODE: dict[str, TaskMode] = {
    "big_tree_nearby": TaskMode.EXCLUSIVE,
    "chest_nearby": TaskMode.EXCLUSIVE,
    "wood_gte_10": TaskMode.EXCLUSIVE,
    "pit_unreachable_ahead": TaskMode.EXCLUSIVE,
    "default": TaskMode.CONCURRENT,
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
    elif trigger == "pit_unreachable_ahead":
        return Sequence(
            children=[
                TriggerCondition(TRIGGER_REGISTRY["pit_unreachable_ahead"], name="PitUnreachable"),
                BuildBridge(),
            ],
            name="Task_build_bridge",
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


class StatefulTaskSelector(Node):
    """Pin an EXCLUSIVE task once it starts running; release on SUCCESS/FAILURE.
    Sets ctx.exclusive_active so terrain tree can defer while EXCLUSIVE is pinned.
    CONCURRENT tasks are re-evaluated each tick (same as DynamicSelector)."""

    def __init__(self, name: str = "TaskExecutor"):
        super().__init__(name)
        self._active_trigger: str | None = None
        self._active_node: Node | None = None
        self._priority_order = ["critical", "high", "medium", "low", "baseline"]

    def tick(self, ctx: TickContext) -> Status:
        if self._active_trigger is not None and TASK_MODE.get(self._active_trigger) == TaskMode.EXCLUSIVE:
            ctx.exclusive_active = True
            status = self._active_node.tick(ctx)
            ctx.bt_trace.append(f"{self.name}>PIN({self._active_trigger})")
            if status != Status.RUNNING:
                self._active_trigger = None
                self._active_node = None
            return status

        sorted_tasks = sorted(
            ctx.task_queue.task_queue,
            key=lambda t: self._priority_order.index(t.priority.value),
        )
        for task in sorted_tasks:
            node = _build_task_subtree(task.trigger, task.action)
            if node is None:
                continue
            status = node.tick(ctx)
            if status == Status.RUNNING:
                if TASK_MODE.get(task.trigger) == TaskMode.EXCLUSIVE:
                    self._active_trigger = task.trigger
                    self._active_node = node
                    ctx.exclusive_active = True
                ctx.bt_trace.append(f"{self.name}>{node.name}")
                return Status.RUNNING
            if status == Status.SUCCESS:
                ctx.bt_trace.append(f"{self.name}>{node.name}")
                return Status.SUCCESS
        return Status.FAILURE

    def reset(self) -> None:
        if self._active_node is not None:
            self._active_node.reset()
        self._active_trigger = None
        self._active_node = None


def build_task_executor():
    return StatefulTaskSelector()
