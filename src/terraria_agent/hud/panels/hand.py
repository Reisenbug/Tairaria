from __future__ import annotations

import dearpygui.dearpygui as dpg

from terraria_agent.hud.state_bridge import HUDSnapshot, StateBridge

KEYS = "hand_keys"


def create(bridge: StateBridge) -> None:
    with dpg.collapsing_header(label="Hand / Input", default_open=True):
        dpg.add_text("held: -", tag=KEYS, wrap=380)


def update(snap: HUDSnapshot) -> None:
    keys = ", ".join(sorted(snap.held_keys)) if snap.held_keys else "-"
    dpg.set_value(KEYS, f"held: {keys}")
