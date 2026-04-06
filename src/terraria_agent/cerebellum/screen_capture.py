from __future__ import annotations

import numpy as np


def _find_terraria_window() -> dict | None:
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGNullWindowID,
        kCGWindowListOptionOnScreenOnly,
    )

    windows = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly, kCGNullWindowID
    )
    for w in windows:
        owner = w.get("kCGWindowOwnerName", "")
        if "Terraria" in owner:
            bounds = w.get("kCGWindowBounds", {})
            return {
                "x": int(bounds.get("X", 0)),
                "y": int(bounds.get("Y", 0)),
                "width": int(bounds.get("Width", 0)),
                "height": int(bounds.get("Height", 0)),
            }
    return None


class ScreenCapture:
    def __init__(self) -> None:
        self._window: dict | None = None

    def refresh_window(self) -> bool:
        self._window = _find_terraria_window()
        return self._window is not None

    @property
    def window_rect(self) -> dict | None:
        return self._window

    def capture(self) -> np.ndarray | None:
        if self._window is None and not self.refresh_window():
            return None

        import mss

        with mss.mss() as sct:
            monitor = {
                "left": self._window["x"],
                "top": self._window["y"],
                "width": self._window["width"],
                "height": self._window["height"],
            }
            shot = sct.grab(monitor)
            frame = np.array(shot)
            return frame[:, :, :3]

    def capture_region(self, rx: float, ry: float, rw: float, rh: float) -> np.ndarray | None:
        frame = self.capture()
        if frame is None:
            return None
        h, w = frame.shape[:2]
        x1 = int(rx * w)
        y1 = int(ry * h)
        x2 = int((rx + rw) * w)
        y2 = int((ry + rh) * h)
        return frame[y1:y2, x1:x2]
