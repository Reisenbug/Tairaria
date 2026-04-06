from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

TEMPLATES_DIR = Path(__file__).parent / "templates"


class DigitMatcher:
    def __init__(self, templates_dir: Path = TEMPLATES_DIR, threshold: float = 0.75) -> None:
        self._threshold = threshold
        self._templates: dict[str, np.ndarray] = {}
        self._load_templates(templates_dir)

    def _load_templates(self, templates_dir: Path) -> None:
        for path in sorted(templates_dir.glob("*.png")):
            name = path.stem
            img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                self._templates[name] = img

    @property
    def loaded(self) -> bool:
        return len(self._templates) >= 10

    def match_digits(self, region: np.ndarray) -> tuple[str, float]:
        if not self._templates:
            return "", 0.0

        if len(region.shape) == 3:
            gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        else:
            gray = region

        matches: list[tuple[int, str, float]] = []
        for name, tmpl in self._templates.items():
            th, tw = tmpl.shape[:2]
            if th > gray.shape[0] or tw > gray.shape[1]:
                continue
            result = cv2.matchTemplate(gray, tmpl, cv2.TM_CCOEFF_NORMED)
            locations = np.where(result >= self._threshold)
            for pt_y, pt_x in zip(*locations):
                matches.append((int(pt_x), name, float(result[pt_y, pt_x])))

        if not matches:
            return "", 0.0

        matches.sort(key=lambda m: m[0])
        merged = self._merge_overlapping(matches)
        text = "".join(m[1] for m in merged)
        avg_conf = sum(m[2] for m in merged) / len(merged) if merged else 0.0
        return text, avg_conf

    def _merge_overlapping(self, matches: list[tuple[int, str, float]]) -> list[tuple[int, str, float]]:
        if not matches:
            return []
        min_spacing = 3
        result = [matches[0]]
        for m in matches[1:]:
            if m[0] - result[-1][0] < min_spacing:
                if m[2] > result[-1][2]:
                    result[-1] = m
            else:
                result.append(m)
        return result

    def parse_value_pair(self, region: np.ndarray) -> tuple[int, int, float]:
        text, conf = self.match_digits(region)
        parts = text.split("/") if "/" in text else None
        if not parts or len(parts) != 2:
            digits_only = "".join(c for c in text if c.isdigit())
            if len(digits_only) >= 2:
                mid = len(digits_only) // 2
                try:
                    return int(digits_only[:mid]), int(digits_only[mid:]), conf
                except ValueError:
                    pass
            return 0, 0, 0.0
        try:
            current = int("".join(c for c in parts[0] if c.isdigit()))
            maximum = int("".join(c for c in parts[1] if c.isdigit()))
            return current, maximum, conf
        except ValueError:
            return 0, 0, 0.0
