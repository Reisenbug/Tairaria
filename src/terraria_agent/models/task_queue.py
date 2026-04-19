from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from terraria_agent.models.goal import Goal


class TaskPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    BASELINE = "baseline"


class Task(BaseModel):
    trigger: str
    action: str
    priority: TaskPriority = TaskPriority.BASELINE
    params: dict = {}


class TaskQueue(BaseModel):
    goal: str
    task_queue: list[Task]
    timestamp: float = 0.0
    stop_biome: str | None = None
    goal_achieved: bool = False
    active_goal: Goal | None = None
