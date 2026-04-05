from terraria_agent.hand.keymap import Keymap, DEFAULT_KEYMAP_PATH


class TestKeymap:
    def test_load_default(self):
        km = Keymap.load()
        assert km.gameplay["left"] == "a"
        assert km.gameplay["right"] == "d"
        assert km.gameplay["jump"] == "space"
        assert km.gameplay["use_item"] == "mouse1"
        assert km.gameplay["interact"] == "mouse2"
        assert km.gameplay["quick_heal"] == "f"

    def test_hotbar_keys(self):
        km = Keymap.load()
        assert km.get_hotbar_key(0) == "1"
        assert km.get_hotbar_key(5) == "6"
        assert km.get_hotbar_key(6) == "z"
        assert km.get_hotbar_key(7) == "x"
        assert km.get_hotbar_key(8) == "c"
        assert km.get_hotbar_key(9) == "v"

    def test_get_gameplay_key(self):
        km = Keymap.load()
        assert km.get_gameplay_key("left") == "a"
        assert km.get_gameplay_key("nonexistent") is None

    def test_save_and_load(self, tmp_path):
        km = Keymap.load()
        km.gameplay["left"] = "h"
        save_path = tmp_path / "custom.json"
        km.save(save_path)
        km2 = Keymap.load(save_path)
        assert km2.gameplay["left"] == "h"
        assert km2.hotbar["7"] == "z"
