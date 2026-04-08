from __future__ import annotations

from pathlib import Path
from typing import Protocol

import pyautogui

from terraria_agent.models.actions import ActionType, GameAction
from terraria_agent.hand.keymap import Keymap
from terraria_agent.hand.key_state import KeyState

pyautogui.PAUSE = 0.0
pyautogui.FAILSAFE = False

MOUSE_BUTTONS = {"mouse1": "left", "mouse2": "right", "mouse3": "middle", "mouse4": "x1", "mouse5": "x2"}


class InputBackend(Protocol):
    def key_down(self, key: str) -> None: ...
    def key_up(self, key: str) -> None: ...
    def press(self, key: str) -> None: ...
    def mouse_down(self, button: str) -> None: ...
    def mouse_up(self, button: str) -> None: ...
    def click(self, x: int | None, y: int | None, button: str) -> None: ...
    def move_to(self, x: int, y: int) -> None: ...


class PyAutoGUIBackend:
    def key_down(self, key: str) -> None:
        pyautogui.keyDown(key)

    def key_up(self, key: str) -> None:
        pyautogui.keyUp(key)

    def mouse_down(self, button: str) -> None:
        pyautogui.mouseDown(button=button)

    def mouse_up(self, button: str) -> None:
        pyautogui.mouseUp(button=button)

    def press(self, key: str) -> None:
        pyautogui.press(key)

    def click(self, x: int | None, y: int | None, button: str) -> None:
        pyautogui.click(x=x, y=y, button=button)

    def move_to(self, x: int, y: int) -> None:
        pyautogui.moveTo(x, y)


class HandController:
    def __init__(
        self,
        keymap: Keymap | None = None,
        backend: InputBackend | None = None,
    ):
        self.keymap = keymap or Keymap.load()
        self.backend = backend or PyAutoGUIBackend()
        self.key_state = KeyState()

    def execute(self, actions: list[GameAction]) -> None:
        desired_holds: set[str] = set()

        for action in actions:
            self._dispatch(action, desired_holds)

        current = self.key_state.held_keys
        for key in current - desired_holds:
            self._release_key(key)
            self.key_state.release(key)

    def release_all(self) -> None:
        for key in self.key_state.release_all():
            self._release_key(key)

    def _release_key(self, key: str) -> None:
        if key.startswith("mouse:"):
            self.backend.mouse_up(key[6:])
        else:
            self.backend.key_up(key)

    def _dispatch(self, action: GameAction, desired_holds: set[str]) -> None:
        match action.action:
            case ActionType.MOVE:
                self._handle_move(action, desired_holds)
            case ActionType.JUMP:
                self._handle_jump()
            case ActionType.ATTACK:
                self._handle_attack(action, desired_holds)
            case ActionType.SWITCH_SLOT:
                self._handle_switch_slot(action)
            case ActionType.USE_ITEM:
                self._handle_use_item(action)
            case ActionType.PLACE_BLOCK:
                self._handle_place_block(action)
            case ActionType.INTERACT:
                self._handle_interact(action)
            case ActionType.CRAFT:
                self._handle_craft()
            case ActionType.PICK_UP:
                pass
            case ActionType.NONE:
                pass

    def _handle_move(self, action: GameAction, desired_holds: set[str]) -> None:
        key = self.keymap.get_gameplay_key(action.direction or "right")
        if not key:
            return
        desired_holds.add(key)
        if self.key_state.press(key):
            self.backend.key_down(key)

    def _handle_jump(self) -> None:
        key = self.keymap.get_gameplay_key("jump")
        if key:
            self.backend.press(key)

    def _handle_attack(self, action: GameAction, desired_holds: set[str]) -> None:
        if action.target and self._screen_safe(action.target):
            self.backend.move_to(int(action.target[0]), int(action.target[1]))
        bind = self.keymap.get_gameplay_key("use_item") or "mouse1"
        if bind in MOUSE_BUTTONS:
            btn = MOUSE_BUTTONS[bind]
            desired_holds.add(f"mouse:{btn}")
            if self.key_state.press(f"mouse:{btn}"):
                self.backend.mouse_down(btn)
        else:
            desired_holds.add(bind)
            if self.key_state.press(bind):
                self.backend.key_down(bind)

    def _handle_switch_slot(self, action: GameAction) -> None:
        if action.slot is None:
            return
        key = self.keymap.get_hotbar_key(action.slot)
        if key:
            self.backend.press(key)

    def _handle_use_item(self, action: GameAction) -> None:
        if action.slot is not None:
            key = self.keymap.get_hotbar_key(action.slot)
            if key:
                self.backend.press(key)
        bind = self.keymap.get_gameplay_key("use_item") or "mouse1"
        if bind in MOUSE_BUTTONS:
            self.backend.click(None, None, MOUSE_BUTTONS[bind])
        else:
            self.backend.press(bind)

    def _handle_place_block(self, action: GameAction) -> None:
        if action.target and self._screen_safe(action.target):
            self.backend.move_to(int(action.target[0]), int(action.target[1]))
        bind = self.keymap.get_gameplay_key("use_item") or "mouse1"
        if bind in MOUSE_BUTTONS:
            self.backend.click(None, None, MOUSE_BUTTONS[bind])
        else:
            self.backend.press(bind)

    def _handle_interact(self, action: GameAction) -> None:
        if action.target and self._screen_safe(action.target):
            self.backend.move_to(int(action.target[0]), int(action.target[1]))
        bind = self.keymap.get_gameplay_key("interact") or "mouse2"
        if bind in MOUSE_BUTTONS:
            self.backend.click(None, None, MOUSE_BUTTONS[bind])
        else:
            self.backend.press(bind)

    def _screen_safe(self, target: tuple) -> bool:
        w, h = pyautogui.size()
        x, y = int(target[0]), int(target[1])
        margin = 10
        return margin <= x <= w - margin and margin <= y <= h - margin

    def _handle_craft(self) -> None:
        key = self.keymap.get_gameplay_key("inventory")
        if key:
            self.backend.press(key)
