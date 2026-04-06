from pathlib import Path

import cv2
import numpy as np
import pytest

from terraria_agent.cerebellum.vision import UIVisionDetector
from terraria_agent.models.game_state import GameState

SCREENSHOTS = Path(__file__).parent.parent.parent / "src" / "terraria_agent" / "pic"

needs_screenshots = pytest.mark.skipif(
    not (SCREENSHOTS / "normal.png").exists(),
    reason="test screenshots not available",
)


class TestUIVisionDetector:
    @needs_screenshots
    def test_detect_returns_game_state(self):
        img = cv2.imread(str(SCREENSHOTS / "normal.png"))
        detector = UIVisionDetector()
        state = detector.detect(img)
        assert isinstance(state, GameState)
        assert state.player.hp == 100
        assert state.player.max_hp == 100

    @needs_screenshots
    def test_detect_inventory_open(self):
        img = cv2.imread(str(SCREENSHOTS / "inventory.png"))
        detector = UIVisionDetector()
        state = detector.detect(img)
        assert state.player.inventory_open is True

    def test_detect_black_frame(self):
        frame = np.zeros((819, 1456, 3), dtype=np.uint8)
        detector = UIVisionDetector()
        state = detector.detect(frame)
        assert state.player.hp == 0
        assert state.player.max_hp == 1

    def test_damage_tracking(self):
        detector = UIVisionDetector()
        frame_full = np.zeros((819, 1456, 3), dtype=np.uint8)
        detector.detect(frame_full)
        state = detector.detect(frame_full)
        assert not state.player.took_damage

    def test_unpopulated_fields_have_defaults(self):
        frame = np.zeros((819, 1456, 3), dtype=np.uint8)
        detector = UIVisionDetector()
        state = detector.detect(frame)
        assert state.enemies == []
        assert state.threats == []
        assert state.objects == []
        assert state.terrain_ahead.value == "flat"

    def test_reset(self):
        detector = UIVisionDetector()
        frame = np.zeros((819, 1456, 3), dtype=np.uint8)
        detector.detect(frame)
        detector.reset()
        state = detector.detect(frame)
        assert not state.player.took_damage
