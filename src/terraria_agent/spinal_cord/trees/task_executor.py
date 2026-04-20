from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Callable

from terraria_agent.spinal_cord.bt import Parallel, Selector, Sequence
from terraria_agent.spinal_cord.bt.core import Node, Status
from terraria_agent.spinal_cord.bt.leaves import Condition
from terraria_agent.spinal_cord.bt.decorators import ForceSuccess
from terraria_agent.spinal_cord.conditions.environment import IsCliffEdge, IsCaveEntrance, HasChestNearby
from terraria_agent.spinal_cord.actions.movement import MoveLeft, MoveRight, MoveToObject, BuildBridge, JumpOverCave
from terraria_agent.spinal_cord.actions.interaction import (
    ShakeTree, ChopBigTree, BigTreeChopped, PickUpValuableDrop,
    OpenChest, EnsureSmartCursorOn, LootAll, MarkChestLooted,
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


_chest_adjacent = HasChestNearby(max_gap=3).check


TRIGGER_REGISTRY: dict[str, Callable[[TickContext], bool]] = {
    "chest_nearby": _chest_adjacent,
    "wood_gte_10": lambda ctx: ctx.game_state.inventory.get("wood", 0) >= 10,
    "default": lambda ctx: True,
}


TASK_MODE: dict[str, TaskMode] = {
    "chest_nearby": TaskMode.EXCLUSIVE,
    "wood_gte_10": TaskMode.EXCLUSIVE,
    "default": TaskMode.CONCURRENT,
}


def _build_goal_subtree(goal_kind: str) -> Node | None:
    if goal_kind == "chop_tree":
        return Sequence(
            children=[
                MoveToObject("tree", reach_tiles=3.0),
                ChopBigTree(),
                BigTreeChopped(),
                PickUpValuableDrop(),
            ],
            name="Goal_chop_tree",
        )
    return None


def _build_task_subtree(trigger: str, action: str) -> Node | None:
    if trigger == "chest_nearby":
        return Sequence(
            children=[
                TriggerCondition(TRIGGER_REGISTRY["chest_nearby"], name="HasChest"),
                MoveToObject("chest"),
                EnsureSmartCursorOn(),
                OpenChest(),
                LootAll(),
                MarkChestLooted(),
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
        return Selector(
            children=[
                Sequence(
                    children=[
                        IsCaveEntrance(name="CaveEntranceAhead"),
                        JumpOverCave(name="SkirtCave"),
                    ],
                    name="CaveSkirt",
                ),
                Sequence(
                    children=[
                        IsCliffEdge(name="CliffEdgeAhead"),
                        ForceSuccess(BuildBridge(), name="BridgeOrHold"),
                    ],
                    name="CliffBridge",
                ),
                Parallel(
                    children=[MoveRight(name="WalkRight"), ShakeTree(name="ShakeTree")],
                    success_threshold=2,
                    name="Walk_shake",
                ),
            ],
            name="Task_walk_shake",
        )
    elif trigger == "default":
        return Selector(
            children=[
                Sequence(
                    children=[
                        IsCaveEntrance(name="CaveEntranceAhead"),
                        JumpOverCave(name="SkirtCave"),
                    ],
                    name="CaveSkirt",
                ),
                Sequence(
                    children=[
                        IsCliffEdge(name="CliffEdgeAhead"),
                        ForceSuccess(BuildBridge(), name="BridgeOrHold"),
                    ],
                    name="CliffBridge",
                ),
                MoveLeft(name="WalkLeft"),
            ],
            name="Task_default_move_left",
        )
    return None


class StatefulTaskSelector(Node):
    """Pin an EXCLUSIVE task once it starts running; release on SUCCESS/FAILURE.
    Sets ctx.exclusive_active so terrain tree can defer while EXCLUSIVE is pinned.
    CONCURRENT tasks are re-evaluated each tick (same as DynamicSelector)."""

    def __init__(self, name: str = "TaskExecutor"):
        super().__init__(name)
        self._active_trigger: str | None = None
        self._active_node: Node | None = None
        self._goal_kind: str | None = None
        self._goal_node: Node | None = None
        self._priority_order = ["critical", "high", "medium", "low", "baseline"]

    def tick(self, ctx: TickContext) -> Status:
        goal = ctx.active_goal
        if goal is not None:
            if self._goal_kind != goal.kind:
                if self._goal_node is not None:
                    self._goal_node.reset()
                self._goal_node = _build_goal_subtree(goal.kind)
                self._goal_kind = goal.kind
            if self._goal_node is not None:
                ctx.exclusive_active = True
                status = self._goal_node.tick(ctx)
                ctx.bt_trace.append(f"{self.name}>GOAL({goal.kind})")
                if status != Status.RUNNING:
                    self._goal_node.reset()
                    self._goal_kind = None
                    self._goal_node = None
                return status
        elif self._goal_node is not None:
            self._goal_node.reset()
            self._goal_kind = None
            self._goal_node = None

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
        if self._goal_node is not None:
            self._goal_node.reset()
        self._goal_kind = None
        self._goal_node = None


def build_task_executor():
    return StatefulTaskSelector()
