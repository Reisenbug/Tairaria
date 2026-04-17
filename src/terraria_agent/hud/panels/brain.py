from __future__ import annotations

import dearpygui.dearpygui as dpg

from terraria_agent.hud.state_bridge import HUDSnapshot, StateBridge

GOAL = "brain_goal"
TASKS = "brain_tasks"
TAC_MSG = "brain_tac_msg"
TAC_IN = "brain_tac_in"
TAC_OUT = "brain_tac_out"


def _truncate(s: str, limit: int = 600) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + f"… (+{len(s) - limit} chars)"


def create(bridge: StateBridge) -> None:
    with dpg.collapsing_header(label="Brain / Tasks", default_open=True):
        dpg.add_text("goal: idle", tag=GOAL, wrap=380)
        dpg.add_text("tasks:\n-", tag=TASKS, wrap=380)

    with dpg.collapsing_header(label="Tactician (AI)", default_open=False):
        dpg.add_text("last: —", tag=TAC_MSG, wrap=380)
        dpg.add_separator()
        dpg.add_text("input:", color=(160, 200, 255))
        dpg.add_text("—", tag=TAC_IN, wrap=380)
        dpg.add_separator()
        dpg.add_text("output:", color=(255, 200, 160))
        dpg.add_text("—", tag=TAC_OUT, wrap=380)


def update(snap: HUDSnapshot) -> None:
    dpg.set_value(GOAL, f"goal: {snap.current_goal}")
    if snap.task_queue_summary:
        body = "\n".join(f"- {t}" for t in snap.task_queue_summary)
    else:
        body = "-"
    dpg.set_value(TASKS, f"tasks:\n{body}")

    dpg.set_value(TAC_MSG, f"last: {snap.tactician_msg or '—'}")
    dpg.set_value(TAC_IN, _truncate(snap.tactician_input) or "—")
    dpg.set_value(TAC_OUT, _truncate(snap.tactician_output) or "—")
