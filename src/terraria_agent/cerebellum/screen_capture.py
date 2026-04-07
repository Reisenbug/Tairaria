from __future__ import annotations

import sys
import threading

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


def _cg_image_to_numpy(cg_image) -> np.ndarray | None:
    from Quartz import (
        CGImageGetBytesPerRow,
        CGImageGetDataProvider,
        CGImageGetHeight,
        CGImageGetWidth,
        CGDataProviderCopyData,
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


def _capture_macos_cg(wid: int) -> np.ndarray | None:
    from Quartz import (
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
    return _cg_image_to_numpy(cg_image)


def _capture_macos_sck(wid: int, timeout: float = 2.0) -> np.ndarray | None:
    """Capture via ScreenCaptureKit — works across Spaces and fullscreen."""
    from ScreenCaptureKit import (
        SCContentFilter,
        SCScreenshotManager,
        SCShareableContent,
        SCStreamConfiguration,
    )

    result_holder: list[np.ndarray | None] = [None]
    event = threading.Event()

    def _on_shareable_content(content, error):
        if error or content is None:
            event.set()
            return

        target_window = None
        for w in content.windows():
            if w.windowID() == wid:
                target_window = w
                break

        if target_window is None:
            event.set()
            return

        content_filter = SCContentFilter.alloc().initWithDesktopIndependentWindow_(target_window)

        config = SCStreamConfiguration.alloc().init()
        config.setWidth_(1920)
        config.setHeight_(1080)
        config.setScalesToFit_(True)
        config.setShowsCursor_(False)

        def _on_image(cg_image, img_error):
            if cg_image is not None:
                result_holder[0] = _cg_image_to_numpy(cg_image)
            event.set()

        SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(
            content_filter, config, _on_image,
        )

    SCShareableContent.getShareableContentWithCompletionHandler_(_on_shareable_content)
    event.wait(timeout=timeout)
    return result_holder[0]


class ScreenCapture:
    def __init__(self) -> None:
        self._window: dict | None = None
        self._use_sck: bool | None = None

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
            wid = self._window["wid"]

            if self._use_sck is None:
                frame = _capture_macos_cg(wid)
                if frame is not None:
                    self._use_sck = False
                    return frame
                frame = _capture_macos_sck(wid)
                if frame is not None:
                    self._use_sck = True
                    return frame
                return None

            if self._use_sck:
                return _capture_macos_sck(wid)
            else:
                frame = _capture_macos_cg(wid)
                if frame is not None:
                    return frame
                self._use_sck = None
                return _capture_macos_sck(wid)

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
