from __future__ import annotations

import dearpygui.dearpygui as dpg

from terraria_agent.hud.state_bridge import HUDSnapshot, StateBridge

BRANCH = "spinal_branch"
STATUS = "spinal_status"
ACTIONS = "spinal_actions"

STATUS_COLORS = {
    "success": (80, 220, 120),
    "running": (80, 180, 255),
    "failure": (255, 110, 110),
    "paused": (200, 200, 80),
    "no-window": (180, 180, 180),
}


def create(bridge: StateBridge) -> None:
    with dpg.collapsing_header(label="Spinal Cord / BT", default_open=True):
        dpg.add_text("branch: -", tag=BRANCH, wrap=380)
        dpg.add_text("status: -", tag=STATUS)
        dpg.add_text("actions:\n-", tag=ACTIONS, wrap=380)


def update(snap: HUDSnapshot) -> None:
    dpg.set_value(BRANCH, f"branch: {snap.active_bt_branch or '-'}")
    dpg.set_value(STATUS, f"status: {snap.bt_status or '-'}")
    dpg.configure_item(STATUS, color=STATUS_COLORS.get(snap.bt_status, (220, 220, 220)))
    if snap.action_buffer:
        body = "\n".join(f"- {a}" for a in snap.action_buffer[-5:])
    else:
        body = "-"
    dpg.set_value(ACTIONS, f"actions:\n{body}")
