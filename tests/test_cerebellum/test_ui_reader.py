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


class TestHeartCounting:
    @needs_screenshots
    def test_normal_5_hearts(self):
        img = cv2.imread(str(SCREENSHOTS / "normal.png"))
        reader = UIReader()
        state = reader.read(img)
        assert state.hp == 100
        assert state.max_hp == 100

    @needs_screenshots
    def test_inventory_5_hearts(self):
        img = cv2.imread(str(SCREENSHOTS / "inventory.png"))
        reader = UIReader()
        state = reader.read(img)
        assert state.hp == 100
        assert state.max_hp == 100

    def test_no_hearts_black_frame(self):
        frame = np.zeros((819, 1456, 3), dtype=np.uint8)
        reader = UIReader()
        state = reader.read(frame)
        assert state.hp == 0
        assert state.max_hp == 0


class TestSelectedSlot:
    @needs_screenshots
    def test_slot_0_selected_normal(self):
        img = cv2.imread(str(SCREENSHOTS / "normal.png"))
        reader = UIReader()
        state = reader.read(img)
        assert state.selected_slot == 0

    @needs_screenshots
    def test_slot_0_selected_inventory(self):
        img = cv2.imread(str(SCREENSHOTS / "inventory.png"))
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
        cfg = UIReaderConfig(heart_min_area=999)
        reader = UIReader(config=cfg)
        assert reader._cfg.heart_min_area == 999
