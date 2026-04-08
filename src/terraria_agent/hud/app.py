from __future__ import annotations

import dearpygui.dearpygui as dpg

from terraria_agent.hud.panels import brain as brain_panel
from terraria_agent.hud.panels import command as command_panel
from terraria_agent.hud.panels import hand as hand_panel
from terraria_agent.hud.panels import log as log_panel
from terraria_agent.hud.panels import spinal_cord as spinal_cord_panel
from terraria_agent.hud.panels import status as status_panel
from terraria_agent.hud.state_bridge import StateBridge

MAIN_WINDOW = "main_window"
PAUSE_BTN = "pause_btn"
STATUS_DOT = "status_dot"
TPS_TEXT = "tps_text"
TICK_TEXT = "tick_text"

_hotkey_listener = None
_last_visible = True


def run_hud(bridge: StateBridge, alpha: float = 0.85) -> None:
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

    with dpg.window(tag=MAIN_WINDOW, no_title_bar=True, no_move=True, no_resize=True, no_collapse=True, label="Terraria Agent", pos=(0, 0), width=420, height=760):
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

    dpg.setup_dearpygui()
    dpg.show_viewport()

    _apply_macos_transparency(alpha)
    _start_hotkey_listener(bridge)
    _focus_terraria()

    bridge.log("[hud] ready — F12 to toggle visibility")

    while dpg.is_dearpygui_running():
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

    _stop_hotkey_listener()
    dpg.destroy_context()


def _apply_macos_transparency(alpha: float) -> None:
    """Use NSWindow.setAlphaValue_ to make DPG window semi-transparent on macOS."""
    try:
        from AppKit import NSApp  # type: ignore
        app = NSApp() if callable(NSApp) else NSApp
        if app is None:
            return
        for w in app.windows():
            title = str(w.title() or "")
            if "Terraria Agent" in title:
                w.setAlphaValue_(alpha)
                w.setOpaque_(False)
                w.setMovableByWindowBackground_(False)
                break
    except Exception as e:
        print(f"[HUD] Transparency unavailable: {e}")


def _focus_terraria() -> None:
    """Activate the Terraria app so it regains keyboard focus after HUD spawn."""
    try:
        from AppKit import NSRunningApplication, NSWorkspace  # type: ignore
        apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.re-logic.terraria")
        if not apps:
            for app in NSWorkspace.sharedWorkspace().runningApplications():
                if "Terraria" in (app.localizedName() or ""):
                    app.activateWithOptions_(0)
                    return
        else:
            apps[0].activateWithOptions_(0)
    except Exception as e:
        print(f"[HUD] Could not focus Terraria: {e}")


def _start_hotkey_listener(bridge: StateBridge) -> None:
    global _hotkey_listener
    try:
        from pynput import keyboard  # type: ignore
    except Exception as e:
        print(f"[HUD] Global hotkey unavailable: {e}")
        return

    def _on_toggle():
        bridge.toggle_visibility()

    def _on_emergency_pause():
        if not bridge.is_paused():
            bridge.set_paused(True)
            bridge.log("[hud] emergency pause (option+shift+p) — agent stopped")

    try:
        _hotkey_listener = keyboard.GlobalHotKeys({
            "<f12>": _on_toggle,
            "<alt>+<shift>+p": _on_emergency_pause,
        })
        _hotkey_listener.daemon = True
        _hotkey_listener.start()
    except Exception as e:
        print(f"[HUD] Failed to start hotkey listener: {e}")
        _hotkey_listener = None


def _stop_hotkey_listener() -> None:
    global _hotkey_listener
    if _hotkey_listener is not None:
        try:
            _hotkey_listener.stop()
        except Exception:
            pass
        _hotkey_listener = None


def _sync_visibility(bridge: StateBridge) -> None:
    global _last_visible
    visible = bridge.is_visible()
    if visible == _last_visible:
        return
    _last_visible = visible
    try:
        from AppKit import NSApp  # type: ignore
        app = NSApp() if callable(NSApp) else NSApp
        if app is None:
            return
        for w in app.windows():
            title = str(w.title() or "")
            if "Terraria Agent" in title:
                if visible:
                    w.orderFront_(None)
                else:
                    w.orderOut_(None)
                break
    except Exception as e:
        print(f"[HUD] Visibility toggle failed: {e}")
