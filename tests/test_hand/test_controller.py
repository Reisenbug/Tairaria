import pytest

from terraria_agent.models.actions import GameAction, ActionType
from terraria_agent.hand.controller import HandController
from terraria_agent.hand.keymap import Keymap


class MockBackend:
    def __init__(self):
        self.log: list[tuple[str, ...]] = []

    def key_down(self, key: str) -> None:
        self.log.append(("key_down", key))

    def key_up(self, key: str) -> None:
        self.log.append(("key_up", key))

    def press(self, key: str) -> None:
        self.log.append(("press", key))

    def click(self, x, y, button: str) -> None:
        self.log.append(("click", x, y, button))

    def move_to(self, x: int, y: int) -> None:
        self.log.append(("move_to", x, y))


@pytest.fixture
def ctrl():
    return HandController(keymap=Keymap.load(), backend=MockBackend())


def _log(ctrl) -> list[tuple]:
    return ctrl.backend.log


class TestMoveActions:
    def test_move_left_holds_a(self, ctrl):
        ctrl.execute([GameAction(action=ActionType.MOVE, direction="left")])
        assert ("key_down", "a") in _log(ctrl)

    def test_move_right_holds_d(self, ctrl):
        ctrl.execute([GameAction(action=ActionType.MOVE, direction="right")])
        assert ("key_down", "d") in _log(ctrl)

    def test_stop_moving_releases_key(self, ctrl):
        ctrl.execute([GameAction(action=ActionType.MOVE, direction="left")])
        ctrl.backend.log.clear()
        ctrl.execute([])
        assert ("key_up", "a") in _log(ctrl)

    def test_switch_direction(self, ctrl):
        ctrl.execute([GameAction(action=ActionType.MOVE, direction="left")])
        ctrl.backend.log.clear()
        ctrl.execute([GameAction(action=ActionType.MOVE, direction="right")])
        assert ("key_up", "a") in _log(ctrl)
        assert ("key_down", "d") in _log(ctrl)


class TestJump:
    def test_jump_presses_space(self, ctrl):
        ctrl.execute([GameAction(action=ActionType.JUMP)])
        assert ("press", "space") in _log(ctrl)


class TestAttack:
    def test_attack_moves_mouse_and_clicks(self, ctrl):
        ctrl.execute([GameAction(action=ActionType.ATTACK, target=(500.0, 300.0))])
        assert ("move_to", 500, 300) in _log(ctrl)
        assert ("click", None, None, "left") in _log(ctrl)

    def test_attack_without_target(self, ctrl):
        ctrl.execute([GameAction(action=ActionType.ATTACK)])
        assert ("click", None, None, "left") in _log(ctrl)


class TestSwitchSlot:
    def test_switch_to_slot_0(self, ctrl):
        ctrl.execute([GameAction(action=ActionType.SWITCH_SLOT, slot=0)])
        assert ("press", "1") in _log(ctrl)

    def test_switch_to_slot_7(self, ctrl):
        ctrl.execute([GameAction(action=ActionType.SWITCH_SLOT, slot=7)])
        assert ("press", "x") in _log(ctrl)


class TestUseItem:
    def test_use_item_slot_and_click(self, ctrl):
        ctrl.execute([GameAction(action=ActionType.USE_ITEM, slot=2)])
        assert ("press", "3") in _log(ctrl)
        assert ("click", None, None, "left") in _log(ctrl)


class TestInteract:
    def test_interact_right_clicks(self, ctrl):
        ctrl.execute([GameAction(action=ActionType.INTERACT, target=(100.0, 200.0))])
        assert ("move_to", 100, 200) in _log(ctrl)
        assert ("click", None, None, "right") in _log(ctrl)


class TestParallelActions:
    def test_move_and_attack_simultaneously(self, ctrl):
        ctrl.execute([
            GameAction(action=ActionType.MOVE, direction="left"),
            GameAction(action=ActionType.ATTACK, target=(500.0, 300.0)),
        ])
        log = _log(ctrl)
        assert ("key_down", "a") in log
        assert ("move_to", 500, 300) in log
        assert ("click", None, None, "left") in log

    def test_move_and_jump(self, ctrl):
        ctrl.execute([
            GameAction(action=ActionType.MOVE, direction="right"),
            GameAction(action=ActionType.JUMP),
        ])
        log = _log(ctrl)
        assert ("key_down", "d") in log
        assert ("press", "space") in log


class TestReleaseAll:
    def test_releases_all_held(self, ctrl):
        ctrl.execute([GameAction(action=ActionType.MOVE, direction="left")])
        ctrl.backend.log.clear()
        ctrl.release_all()
        assert ("key_up", "a") in _log(ctrl)
        assert ctrl.key_state.held_keys == frozenset()


class TestNoneAndPickUp:
    def test_none_action(self, ctrl):
        ctrl.execute([GameAction(action=ActionType.NONE)])
        assert _log(ctrl) == []

    def test_pick_up_is_noop(self, ctrl):
        ctrl.execute([GameAction(action=ActionType.PICK_UP)])
        assert _log(ctrl) == []
