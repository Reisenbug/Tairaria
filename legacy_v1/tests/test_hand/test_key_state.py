from terraria_agent.hand.key_state import KeyState


class TestKeyState:
    def test_press_new_key(self):
        ks = KeyState()
        assert ks.press("a") is True
        assert ks.is_held("a")

    def test_press_already_held(self):
        ks = KeyState()
        ks.press("a")
        assert ks.press("a") is False

    def test_release_held(self):
        ks = KeyState()
        ks.press("a")
        assert ks.release("a") is True
        assert not ks.is_held("a")

    def test_release_not_held(self):
        ks = KeyState()
        assert ks.release("a") is False

    def test_release_all(self):
        ks = KeyState()
        ks.press("a")
        ks.press("d")
        released = ks.release_all()
        assert set(released) == {"a", "d"}
        assert ks.held_keys == frozenset()

    def test_held_keys_immutable(self):
        ks = KeyState()
        ks.press("a")
        keys = ks.held_keys
        assert isinstance(keys, frozenset)
