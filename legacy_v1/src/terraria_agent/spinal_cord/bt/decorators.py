from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .core import Node, Status

if TYPE_CHECKING:
    from terraria_agent.spinal_cord.context import TickContext


class Inverter(Node):
    """Invert child result: SUCCESS↔FAILURE, RUNNING stays."""

    def __init__(self, child: Node, name: str = ""):
        super().__init__(name)
        self.child = child

    def tick(self, ctx: TickContext) -> Status:
        status = self.child.tick(ctx)
        if status == Status.SUCCESS:
            return Status.FAILURE
        if status == Status.FAILURE:
            return Status.SUCCESS
        return Status.RUNNING

    def reset(self) -> None:
        self.child.reset()


class RepeatUntilFail(Node):
    """Tick child repeatedly (within one tick call) until it returns FAILURE.
    Returns SUCCESS when child eventually fails. Returns RUNNING if child returns RUNNING."""

    def __init__(self, child: Node, name: str = ""):
        super().__init__(name)
        self.child = child

    def tick(self, ctx: TickContext) -> Status:
        status = self.child.tick(ctx)
        if status == Status.FAILURE:
            return Status.SUCCESS
        if status == Status.RUNNING:
            return Status.RUNNING
        return Status.RUNNING

    def reset(self) -> None:
        self.child.reset()


class Cooldown(Node):
    """After child succeeds, block re-execution for `duration` seconds."""

    def __init__(self, child: Node, duration: float, name: str = "", clock: object = None):
        super().__init__(name)
        self.child = child
        self.duration = duration
        self._last_success: float | None = None
        self._clock = clock

    def _now(self) -> float:
        if self._clock is not None:
            return self._clock()  # type: ignore[operator]
        return time.monotonic()

    def tick(self, ctx: TickContext) -> Status:
        if self._last_success is not None:
            if self._now() - self._last_success < self.duration:
                return Status.FAILURE
        status = self.child.tick(ctx)
        if status == Status.SUCCESS:
            self._last_success = self._now()
        return status

    def reset(self) -> None:
        self._last_success = None
        self.child.reset()


class ForceSuccess(Node):
    """Always return SUCCESS regardless of child result (unless RUNNING)."""

    def __init__(self, child: Node, name: str = ""):
        super().__init__(name)
        self.child = child

    def tick(self, ctx: TickContext) -> Status:
        status = self.child.tick(ctx)
        if status == Status.RUNNING:
            return Status.RUNNING
        return Status.SUCCESS

    def reset(self) -> None:
        self.child.reset()
