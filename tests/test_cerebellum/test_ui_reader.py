from pathlib import Path

import cv2
import numpy as np
import pytest

from terraria_agent.cerebellum.ui_reader import UIReader, UIReaderConfig, UIState

SCREENSHOTS = Path(__file__).parent.parent.parent / "src" / "terraria_agent" / "pic"


def _has_screenshots() -> bool:
    return (SCREENSHOTS / "normal.png").exists()


needs_screenshots = pytest.mark.skipif(
    not _has_screenshots(), reason="test screenshots not available"
)


class TestHPReading:
    def test_black_frame_returns_zero(self):
        frame = np.zeros((819, 1456, 3), dtype=np.uint8)
        reader = UIReader()
        state = reader.read(frame)
        assert state.hp == 0

    def test_last_max_hp_cached(self):
        reader = UIReader()
        reader._last_max_hp = 200
        frame = np.zeros((819, 1456, 3), dtype=np.uint8)
        state = reader.read(frame)
        assert state.max_hp == 200


class TestSelectedSlot:
    @needs_screenshots
    def test_slot_0_selected_normal(self):
        img = cv2.imread(str(SCREENSHOTS / "normal.png"))
        reader = UIReader()
        state = reader.read(img)
        assert state.selected_slot == 0


class TestInventoryOpen:
    @needs_screenshots
    def test_inventory_closed(self):
        img = cv2.imread(str(SCREENSHOTS / "normal.png"))
        reader = UIReader()
        state = reader.read(img)
        assert state.inventory_open is False

    @needs_screenshots
    def test_inventory_open(self):
        img = cv2.imread(str(SCREENSHOTS / "inventory.png"))
        reader = UIReader()
        state = reader.read(img)
        assert state.inventory_open is True


class TestConfigOverride:
    def test_custom_config(self):
        cfg = UIReaderConfig(ocr_scale=2)
        reader = UIReader(config=cfg)
        assert reader._cfg.ocr_scale == 2
