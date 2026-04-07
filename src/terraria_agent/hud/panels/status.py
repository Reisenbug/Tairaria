from __future__ import annotations

import dearpygui.dearpygui as dpg

from terraria_agent.hud.state_bridge import HUDSnapshot, StateBridge

HP_BAR = "status_hp_bar"
HP_TEXT = "status_hp_text"
DANGER = "status_danger"
TREND = "status_trend"
SLOT = "status_slot"
BUFFS = "status_buffs"
INVENTORY = "status_inventory"

DANGER_COLORS = {
    "safe": (80, 220, 120),
    "warning": (255, 180, 60),
    "critical": (255, 70, 70),
}


def create(bridge: StateBridge) -> None:
    with dpg.collapsing_header(label="Cerebellum / Status", default_open=True):
        dpg.add_progress_bar(tag=HP_BAR, default_value=0.0, overlay="0/0", width=-1)
        dpg.add_text("HP: --", tag=HP_TEXT)
        dpg.add_text("danger: safe", tag=DANGER, color=DANGER_COLORS["safe"])
        dpg.add_text("trend: stable", tag=TREND)
        dpg.add_text("slot: 0", tag=SLOT)
        dpg.add_text("buffs: -", tag=BUFFS)
        dpg.add_text("inventory: closed", tag=INVENTORY)


def update(snap: HUDSnapshot) -> None:
    ratio = snap.hp / snap.max_hp if snap.max_hp > 0 else 0.0
    dpg.set_value(HP_BAR, ratio)
    dpg.configure_item(HP_BAR, overlay=f"{snap.hp}/{snap.max_hp}")
    dpg.set_value(HP_TEXT, f"HP: {snap.hp}/{snap.max_hp}")
    color = DANGER_COLORS.get(snap.danger_level, (200, 200, 200))
    dpg.set_value(DANGER, f"danger: {snap.danger_level}")
    dpg.configure_item(DANGER, color=color)
    dpg.set_value(TREND, f"trend: {snap.hp_trend}")
    dpg.set_value(SLOT, f"slot: {snap.selected_slot}")
    dpg.set_value(BUFFS, f"buffs: {', '.join(snap.buffs) if snap.buffs else '-'}")
    dpg.set_value(INVENTORY, f"inventory: {'open' if snap.inventory_open else 'closed'}")
