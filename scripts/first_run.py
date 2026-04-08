"""
First real run: starts the agent with a 'walk left' default task.

Usage:
    python scripts/first_run.py

Flow:
    1. HUD window spawns
    2. Auto-focuses Terraria (3s delay for you to switch desktops if needed)
    3. Agent loop starts ticking — player walks left

Controls:
    - Type 'pause' in the command box to stop movement
    - F12 to toggle HUD visibility
    - Close HUD window to exit
"""
from __future__ import annotations

import os
import sys
import time

import dearpygui.dearpygui as dpg

from terraria_agent.hud.app import (
    MAIN_WINDOW,
    PAUSE_BTN,
    STATUS_DOT,
    TICK_TEXT,
    TPS_TEXT,
    _apply_macos_transparency,
    _start_hotkey_listener,
    _stop_hotkey_listener,
    _sync_visibility,
    _focus_terraria,
)
from terraria_agent.hud.panels import brain as brain_panel
from terraria_agent.hud.panels import command as command_panel
from terraria_agent.hud.panels import hand as hand_panel
from terraria_agent.hud.panels import log as log_panel
from terraria_agent.hud.panels import spinal_cord as spinal_cord_panel
from terraria_agent.hud.panels import status as status_panel
from terraria_agent.hud.state_bridge import StateBridge
from terraria_agent.models.task_queue import Task, TaskPriority, TaskQueue
from terraria_agent.orchestrator.agent_loop import AgentOrchestrator


FOCUS_DELAY = 3.0


def main() -> None:
    bridge = StateBridge()

    detector = None
    source = os.environ.get("TERRARIA_AGENT_DETECTOR", "terra_blind").lower()
    if source == "terra_blind":
        from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient
        detector = TerraBlindClient()

    orch = AgentOrchestrator(bridge, tick_rate=5.0, detector=detector)
    orch._task_queue = TaskQueue(
        goal="walk left",
        task_queue=[
            Task(trigger="default", action="move_left", priority=TaskPriority.BASELINE),
        ],
    )

    bridge.log("[first_run] HUD ready — focusing Terraria in 3s...")
    bridge.log("[first_run] Player will walk left after focus switch")
    bridge.log("[first_run] Type 'pause' in command box to stop")

    dpg.create_context()
    dpg.create_viewport(
        title="Terraria Agent HUD",
        width=420,
        height=760,
        always_on_top=True,
        clear_color=(18, 18, 28, 230),
    )

    def _toggle_pause():
        bridge.toggle_pause()
        label = "Resume" if bridge.is_paused() else "Pause"
        dpg.configure_item(PAUSE_BTN, label=label)

    with dpg.window(tag=MAIN_WINDOW, no_title_bar=False, label="Terraria Agent"):
        with dpg.group(horizontal=True):
            dpg.add_button(label="Pause", tag=PAUSE_BTN, callback=_toggle_pause)
            dpg.add_text("●", tag=STATUS_DOT, color=(0, 255, 0))
            dpg.add_text("0.0 TPS", tag=TPS_TEXT)
            dpg.add_text("tick 0", tag=TICK_TEXT)
        status_panel.create(bridge)
        spinal_cord_panel.create(bridge)
        hand_panel.create(bridge)
        brain_panel.create(bridge)
        command_panel.create(bridge)
        log_panel.create(bridge)

    dpg.set_primary_window(MAIN_WINDOW, True)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    _apply_macos_transparency(0.85)
    _start_hotkey_listener(bridge)

    focus_done = False
    agent_started = False
    hud_start_time = time.monotonic()

    try:
        while dpg.is_dearpygui_running():
            now = time.monotonic()
            elapsed = now - hud_start_time

            if not focus_done and elapsed >= FOCUS_DELAY:
                _focus_terraria()
                bridge.log("[first_run] Focused Terraria — starting agent")
                focus_done = True

            if focus_done and not agent_started:
                orch.start()
                agent_started = True

            snap = bridge.get_snapshot()
            if snap is not None:
                status_panel.update(snap)
                spinal_cord_panel.update(snap)
                hand_panel.update(snap)
                brain_panel.update(snap)
                dpg.set_value(TPS_TEXT, f"{snap.tps:.1f} TPS")
                dpg.set_value(TICK_TEXT, f"tick {snap.tick_count}")
                dot_color = (255, 180, 60) if bridge.is_paused() else (80, 220, 120)
                dpg.configure_item(STATUS_DOT, color=dot_color)
            log_panel.update(bridge.drain_logs())
            _sync_visibility(bridge)
            dpg.render_dearpygui_frame()
    finally:
        orch.stop()
        _stop_hotkey_listener()
        dpg.destroy_context()


if __name__ == "__main__":
    main()
