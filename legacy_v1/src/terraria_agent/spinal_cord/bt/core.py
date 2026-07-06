from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from terraria_agent.spinal_cord.context import TickContext


class Status(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    RUNNING = "running"


class Node(ABC):
    def __init__(self, name: str = ""):
        self.name = name or self.__class__.__name__

    @abstractmethod
    def tick(self, ctx: TickContext) -> Status: ...

    def reset(self) -> None:
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.name!r})"
