from __future__ import annotations

from collections import deque

import dearpygui.dearpygui as dpg

from terraria_agent.hud.state_bridge import StateBridge

LOG_TAG = "log_text"
_MAX_LINES = 200
_lines: deque[str] = deque(maxlen=_MAX_LINES)


def create(bridge: StateBridge) -> None:
    with dpg.collapsing_header(label="Log", default_open=True):
        dpg.add_input_text(
            tag=LOG_TAG,
            default_value="",
            multiline=True,
            readonly=True,
            width=-1,
            height=140,
        )


def update(new_lines: list[str]) -> None:
    if not new_lines:
        return
    _lines.extend(new_lines)
    at_bottom = dpg.get_y_scroll(LOG_TAG) >= dpg.get_y_scroll_max(LOG_TAG) - 2
    dpg.set_value(LOG_TAG, "\n".join(_lines))
    if at_bottom:
        dpg.set_y_scroll(LOG_TAG, dpg.get_y_scroll_max(LOG_TAG))
