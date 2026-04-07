from __future__ import annotations

from collections import deque

import dearpygui.dearpygui as dpg

from terraria_agent.hud.state_bridge import StateBridge

LOG_TAG = "log_text"
_MAX_LINES = 200
_lines: deque[str] = deque(maxlen=_MAX_LINES)


def create(bridge: StateBridge) -> None:
    with dpg.collapsing_header(label="Log", default_open=True):
        with dpg.child_window(height=140, autosize_x=True):
            dpg.add_text("", tag=LOG_TAG, wrap=380)


def update(new_lines: list[str]) -> None:
    if not new_lines:
        return
    _lines.extend(new_lines)
    dpg.set_value(LOG_TAG, "\n".join(_lines))
