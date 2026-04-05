from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from .core import Node, Status

if TYPE_CHECKING:
    from terraria_agent.spinal_cord.context import TickContext


class Sequence(Node):
    """Run children in order. Fail on first FAILURE, return RUNNING if any child is RUNNING."""

    def __init__(self, children: list[Node], name: str = ""):
        super().__init__(name)
        self.children = children
        self._running_idx = 0

    def tick(self, ctx: TickContext) -> Status:
        for i in range(self._running_idx, len(self.children)):
            status = self.children[i].tick(ctx)
            if status == Status.FAILURE:
                self._running_idx = 0
                return Status.FAILURE
            if status == Status.RUNNING:
                self._running_idx = i
                return Status.RUNNING
        self._running_idx = 0
        return Status.SUCCESS

    def reset(self) -> None:
        self._running_idx = 0
        for child in self.children:
            child.reset()


class Selector(Node):
    """Try children in order. Succeed on first SUCCESS, return RUNNING if any child is RUNNING."""

    def __init__(self, children: list[Node], name: str = ""):
        super().__init__(name)
        self.children = children
        self._running_idx = 0

    def tick(self, ctx: TickContext) -> Status:
        for i in range(self._running_idx, len(self.children)):
            status = self.children[i].tick(ctx)
            if status == Status.SUCCESS:
                self._running_idx = 0
                return Status.SUCCESS
            if status == Status.RUNNING:
                self._running_idx = i
                return Status.RUNNING
        self._running_idx = 0
        return Status.FAILURE

    def reset(self) -> None:
        self._running_idx = 0
        for child in self.children:
            child.reset()


class PrioritySelector(Node):
    """Like Selector but re-evaluates from the highest priority child each tick.
    If a higher-priority child activates, the previously running lower-priority child is reset."""

    def __init__(self, children: list[Node], name: str = ""):
        super().__init__(name)
        self.children = children
        self._last_running_idx: int | None = None

    def tick(self, ctx: TickContext) -> Status:
        for i, child in enumerate(self.children):
            status = child.tick(ctx)
            if status == Status.SUCCESS:
                self._reset_running(i)
                return Status.SUCCESS
            if status == Status.RUNNING:
                self._reset_running(i)
                self._last_running_idx = i
                return Status.RUNNING
        self._reset_running(None)
        return Status.FAILURE

    def _reset_running(self, new_idx: int | None) -> None:
        if self._last_running_idx is not None and self._last_running_idx != new_idx:
            self.children[self._last_running_idx].reset()
        if new_idx is None:
            self._last_running_idx = None

    def reset(self) -> None:
        self._last_running_idx = None
        for child in self.children:
            child.reset()


class Parallel(Node):
    """Run all children every tick. Succeeds when >= success_threshold children succeed.
    Fails when enough children fail that the threshold is unreachable."""

    def __init__(self, children: list[Node], success_threshold: int | None = None, name: str = ""):
        super().__init__(name)
        self.children = children
        self.success_threshold = success_threshold or len(children)

    def tick(self, ctx: TickContext) -> Status:
        successes = 0
        failures = 0
        for child in self.children:
            status = child.tick(ctx)
            if status == Status.SUCCESS:
                successes += 1
            elif status == Status.FAILURE:
                failures += 1
        if successes >= self.success_threshold:
            return Status.SUCCESS
        if failures > len(self.children) - self.success_threshold:
            return Status.FAILURE
        return Status.RUNNING

    def reset(self) -> None:
        for child in self.children:
            child.reset()


class DynamicSelector(Node):
    """Builds children dynamically from a provider function each tick.
    Used to consume Brain's TaskQueue — the provider reads the queue and returns nodes."""

    def __init__(self, provider: Callable[[TickContext], list[Node]], name: str = ""):
        super().__init__(name)
        self.provider = provider
        self._children: list[Node] = []
        self._running_idx: int | None = None

    def tick(self, ctx: TickContext) -> Status:
        new_children = self.provider(ctx)
        if new_children is not self._children:
            if self._running_idx is not None and self._running_idx < len(self._children):
                self._children[self._running_idx].reset()
            self._children = new_children
            self._running_idx = None

        for i, child in enumerate(self._children):
            status = child.tick(ctx)
            if status == Status.SUCCESS:
                self._running_idx = None
                return Status.SUCCESS
            if status == Status.RUNNING:
                self._running_idx = i
                return Status.RUNNING
        self._running_idx = None
        return Status.FAILURE

    def reset(self) -> None:
        if self._running_idx is not None and self._running_idx < len(self._children):
            self._children[self._running_idx].reset()
        self._children = []
        self._running_idx = None
