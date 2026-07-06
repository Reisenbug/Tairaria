from __future__ import annotations


class KeyState:
    """Tracks which keys are currently held down to avoid redundant press/release."""

    def __init__(self):
        self._held: set[str] = set()

    @property
    def held_keys(self) -> frozenset[str]:
        return frozenset(self._held)

    def is_held(self, key: str) -> bool:
        return key in self._held

    def press(self, key: str) -> bool:
        """Mark key as held. Returns True if key was not already held."""
        if key in self._held:
            return False
        self._held.add(key)
        return True

    def release(self, key: str) -> bool:
        """Mark key as released. Returns True if key was held."""
        if key not in self._held:
            return False
        self._held.discard(key)
        return True

    def release_all(self) -> list[str]:
        """Release all held keys. Returns list of keys that were released."""
        released = list(self._held)
        self._held.clear()
        return released
