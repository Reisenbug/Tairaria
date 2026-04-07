from __future__ import annotations

import sys

import numpy as np


def _find_terraria_window() -> dict | None:
    if sys.platform == "darwin":
        return _find_terraria_window_macos()
    if sys.platform == "win32":
        return _find_terraria_window_windows()
    return None


def _find_terraria_window_macos() -> dict | None:
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGNullWindowID,
        kCGWindowListOptionAll,
    )

    windows = CGWindowListCopyWindowInfo(kCGWindowListOptionAll, kCGNullWindowID)
    best = None
    best_area = 0
    for w in windows:
        owner = w.get("kCGWindowOwnerName", "")
        if "Terraria" not in owner:
            continue
        bounds = w.get("kCGWindowBounds", {})
        width = int(bounds.get("Width", 0))
        height = int(bounds.get("Height", 0))
        area = width * height
        if area > best_area:
            best_area = area
            best = {
                "x": int(bounds.get("X", 0)),
                "y": int(bounds.get("Y", 0)),
                "width": width,
                "height": height,
                "wid": int(w.get("kCGWindowNumber", 0)),
            }
    return best


def _find_terraria_window_windows() -> dict | None:
    import ctypes

    user32 = ctypes.windll.user32

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                     ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    hwnd = user32.FindWindowW(None, "Terraria: Terraria")
    if not hwnd:
        hwnd = user32.FindWindowW(None, "Terraria")
    if not hwnd:
        results = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def _enum_cb(h, _):
            length = user32.GetWindowTextLengthW(h)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(h, buf, length + 1)
                if "Terraria" in buf.value:
                    results.append(h)
            return True

        user32.EnumWindows(_enum_cb, 0)
        hwnd = results[0] if results else None

    if not hwnd:
        return None

    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return {
        "x": rect.left,
        "y": rect.top,
        "width": rect.right - rect.left,
        "height": rect.bottom - rect.top,
    }


def _capture_macos_cg(wid: int) -> np.ndarray | None:
    from Quartz import (
        CGImageGetBytesPerRow,
        CGImageGetDataProvider,
        CGImageGetHeight,
        CGImageGetWidth,
        CGDataProviderCopyData,
        CGRectNull,
        CGWindowListCreateImage,
        kCGWindowImageBoundsIgnoreFraming,
        kCGWindowListOptionIncludingWindow,
    )

    cg_image = CGWindowListCreateImage(
        CGRectNull,
        kCGWindowListOptionIncludingWindow,
        wid,
        kCGWindowImageBoundsIgnoreFraming,
    )
    if cg_image is None:
        return None

    w = CGImageGetWidth(cg_image)
    h = CGImageGetHeight(cg_image)
    bpr = CGImageGetBytesPerRow(cg_image)
    data_provider = CGImageGetDataProvider(cg_image)
    raw = CGDataProviderCopyData(data_provider)
    arr = np.frombuffer(raw, dtype=np.uint8).reshape((h, bpr // 4, 4))
    bgra = arr[:h, :w, :]
    return bgra[:, :, [2, 1, 0]]


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

        if sys.platform == "darwin" and "wid" in self._window:
            frame = _capture_macos_cg(self._window["wid"])
            if frame is not None:
                return frame

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
