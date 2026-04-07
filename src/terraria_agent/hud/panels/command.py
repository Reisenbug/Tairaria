from __future__ import annotations

import dearpygui.dearpygui as dpg

from terraria_agent.hud.state_bridge import StateBridge

INPUT = "cmd_input"
HINT = (
    "commands:\n"
    "  goal: <text>\n"
    "  task: <trigger> <action> [priority]\n"
    "  clear | pause | resume"
)


def create(bridge: StateBridge) -> None:
    def _submit(sender=None, app_data=None, user_data=None):
        text = dpg.get_value(INPUT)
        if text:
            bridge.send_command(text)
            dpg.set_value(INPUT, "")

    with dpg.collapsing_header(label="Command", default_open=True):
        dpg.add_input_text(
            tag=INPUT,
            hint="goal: <text>",
            on_enter=True,
            callback=_submit,
            width=-1,
        )
        dpg.add_button(label="Send", callback=_submit, width=-1)
        dpg.add_text(HINT, color=(160, 160, 160))
