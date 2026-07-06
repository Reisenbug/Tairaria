from __future__ import annotations

from collections import deque

import dearpygui.dearpygui as dpg

from terraria_agent.hud.state_bridge import StateBridge

LOG_TAG = "log_text"
LOG_SCROLL = "log_scroll"
_MAX_LINES = 200
_lines: deque[str] = deque(maxlen=_MAX_LINES)
_SNAP_THRESHOLD = 8


def create(bridge: StateBridge) -> None:
    with dpg.collapsing_header(label="Log", default_open=True):
        with dpg.child_window(tag=LOG_SCROLL, height=140, autosize_x=True):
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
    scroll_max = dpg.get_y_scroll_max(LOG_SCROLL)
    at_bottom = scroll_max <= 0 or dpg.get_y_scroll(LOG_SCROLL) >= scroll_max - _SNAP_THRESHOLD
    _lines.extend(new_lines)
    dpg.set_value(LOG_TAG, "\n".join(_lines))
    if at_bottom:
        dpg.set_y_scroll(LOG_SCROLL, -1.0)
