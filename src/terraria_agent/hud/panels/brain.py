from __future__ import annotations

import dearpygui.dearpygui as dpg

from terraria_agent.hud.state_bridge import HUDSnapshot, StateBridge

GOAL = "brain_goal"
TASKS = "brain_tasks"


def create(bridge: StateBridge) -> None:
    with dpg.collapsing_header(label="Brain / Tasks", default_open=True):
        dpg.add_text("goal: idle", tag=GOAL, wrap=380)
        dpg.add_text("tasks:\n-", tag=TASKS, wrap=380)


def update(snap: HUDSnapshot) -> None:
    dpg.set_value(GOAL, f"goal: {snap.current_goal}")
    if snap.task_queue_summary:
        body = "\n".join(f"- {t}" for t in snap.task_queue_summary)
    else:
        body = "-"
    dpg.set_value(TASKS, f"tasks:\n{body}")
