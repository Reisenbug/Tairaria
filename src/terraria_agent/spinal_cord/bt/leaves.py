from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from .core import Node, Status

if TYPE_CHECKING:
    from terraria_agent.spinal_cord.context import TickContext


class Condition(Node):
    """Leaf node that checks a predicate on the game state.
    Returns SUCCESS if the condition is met, FAILURE otherwise. Never RUNNING."""

    @abstractmethod
    def check(self, ctx: TickContext) -> bool: ...

    def tick(self, ctx: TickContext) -> Status:
        return Status.SUCCESS if self.check(ctx) else Status.FAILURE


class Action(Node):
    """Leaf node that produces action commands.
    Appends GameAction(s) to ctx.action_buffer.
    Returns SUCCESS when done, RUNNING if multi-tick, FAILURE if impossible."""

    @abstractmethod
    def execute(self, ctx: TickContext) -> Status: ...

    def tick(self, ctx: TickContext) -> Status:
        return self.execute(ctx)
