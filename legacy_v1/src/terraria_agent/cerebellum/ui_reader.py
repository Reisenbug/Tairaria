from __future__ import annotations

import re
from dataclasses import dataclass, field

import cv2
import numpy as np
import pytesseract


@dataclass
class UIState:
    hp: int = 0
    max_hp: int = 0
    selected_slot: int = 0
    buff_active: bool = False
    inventory_open: bool = False


@dataclass
class UIReaderConfig:
    life_text_region: tuple[float, float, float, float] = (0.82, 0.0, 0.14, 0.03)
    hotbar_region: tuple[float, float, float, float] = (0.032, 0.017, 0.261, 0.046)
    buff_region: tuple[float, float, float, float] = (0.01, 0.066, 0.20, 0.032)
    inventory_region: tuple[float, float, float, float] = (0.03, 0.08, 0.25, 0.15)
    hotbar_yellow_lower: list[int] = field(default_factory=lambda: [20, 180, 180])
    hotbar_yellow_upper: list[int] = field(default_factory=lambda: [35, 255, 255])
    inventory_bg_lower: list[int] = field(default_factory=lambda: [105, 100, 100])
    inventory_bg_upper: list[int] = field(default_factory=lambda: [125, 180, 180])
    buff_std_threshold: float = 25.0
    inventory_ratio_threshold: float = 0.3
    ocr_scale: int = 4
    ocr_thresholds: list[int] = field(default_factory=lambda: [140, 150, 160])


_HP_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
_TESS_CFG = "--psm 7 -c tessedit_char_whitelist=0123456789/"


class UIReader:
    HOTBAR_SLOTS = 10

    def __init__(self, config: UIReaderConfig | None = None) -> None:
        self._cfg = config or UIReaderConfig()
        self._last_max_hp: int = 100

    def read(self, frame: np.ndarray) -> UIState:
        h, w = frame.shape[:2]
        hp, max_hp = self._read_hp_ocr(frame, w, h)
        selected_slot = self._read_selected_slot(frame, w, h)
        buff_active = self._read_buff_active(frame, w, h)
        inventory_open = self._read_inventory_open(frame, w, h)
        return UIState(
            hp=hp,
            max_hp=max_hp,
            selected_slot=selected_slot,
            buff_active=buff_active,
            inventory_open=inventory_open,
        )

    def _crop(self, frame: np.ndarray, region: tuple[float, float, float, float], w: int, h: int) -> np.ndarray:
        rx, ry, rw, rh = region
        x1, y1 = int(rx * w), int(ry * h)
        x2, y2 = int((rx + rw) * w), int((ry + rh) * h)
        return frame[y1:y2, x1:x2]

    def _read_hp_ocr(self, frame: np.ndarray, w: int, h: int) -> tuple[int, int]:
        roi = self._crop(frame, self._cfg.life_text_region, w, h)
        if roi.size == 0:
            return 0, self._last_max_hp
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=self._cfg.ocr_scale, fy=self._cfg.ocr_scale, interpolation=cv2.INTER_CUBIC)

        votes: dict[tuple[int, int], int] = {}
        for t in self._cfg.ocr_thresholds:
            _, thresh = cv2.threshold(gray, t, 255, cv2.THRESH_BINARY)
            text = pytesseract.image_to_string(thresh, config=_TESS_CFG).strip()
            m = _HP_RE.search(text)
            if m:
                pair = (int(m.group(1)), int(m.group(2)))
                votes[pair] = votes.get(pair, 0) + 1

        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        text = pytesseract.image_to_string(otsu, config=_TESS_CFG).strip()
        m = _HP_RE.search(text)
        if m:
            pair = (int(m.group(1)), int(m.group(2)))
            votes[pair] = votes.get(pair, 0) + 2

        if not votes:
            return 0, self._last_max_hp

        best = max(votes, key=lambda k: votes[k])
        hp, max_hp = best
        if max_hp > 0:
            self._last_max_hp = max_hp
        else:
            max_hp = self._last_max_hp
        hp = min(hp, max_hp)
        return hp, max_hp

    def _read_selected_slot(self, frame: np.ndarray, w: int, h: int) -> int:
        hotbar = self._crop(frame, self._cfg.hotbar_region, w, h)
        hsv = cv2.cvtColor(hotbar, cv2.COLOR_BGR2HSV)
        hb_w = hotbar.shape[1]
        slot_width = hb_w / self.HOTBAR_SLOTS
        yellow_lo = np.array(self._cfg.hotbar_yellow_lower)
        yellow_hi = np.array(self._cfg.hotbar_yellow_upper)
        best_slot = 0
        best_score = 0.0
        for i in range(self.HOTBAR_SLOTS):
            x1 = int(i * slot_width)
            x2 = int((i + 1) * slot_width)
            slot_hsv = hsv[:, x1:x2]
            mask = cv2.inRange(slot_hsv, yellow_lo, yellow_hi)
            score = float(np.sum(mask)) / max(mask.size, 1)
            if score > best_score:
                best_score = score
                best_slot = i
        return best_slot

    def _read_buff_active(self, frame: np.ndarray, w: int, h: int) -> bool:
        region = self._crop(frame, self._cfg.buff_region, w, h)
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        std = float(np.std(gray))
        return std > self._cfg.buff_std_threshold

    def _read_inventory_open(self, frame: np.ndarray, w: int, h: int) -> bool:
        region = self._crop(frame, self._cfg.inventory_region, w, h)
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        inv_lo = np.array(self._cfg.inventory_bg_lower)
        inv_hi = np.array(self._cfg.inventory_bg_upper)
        mask = cv2.inRange(hsv, inv_lo, inv_hi)
        ratio = float(np.sum(mask > 0)) / max(mask.size, 1)
        return ratio > self._cfg.inventory_ratio_threshold
