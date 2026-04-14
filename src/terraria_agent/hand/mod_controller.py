from __future__ import annotations

import json
import urllib.request

import pyautogui

from terraria_agent.hand.key_state import KeyState
from terraria_agent.models.actions import ActionType, GameAction

pyautogui.PAUSE = 0.0
pyautogui.FAILSAFE = False

_CONTROL_URL = "http://127.0.0.1:17878/control"
_NO_PROXY_HANDLER = urllib.request.ProxyHandler({})
_OPENER = urllib.request.build_opener(_NO_PROXY_HANDLER)

_QUICK_HEAL_URL = "http://127.0.0.1:17878/quick_heal"
_LOOT_ALL_URL = "http://127.0.0.1:17878/loot_all"


class ModController:
    def __init__(self, mouse_control_flag=None):
        self.key_state = KeyState()
        self._mouse_enabled = mouse_control_flag or (lambda: True)

    def execute(self, actions: list[GameAction]) -> None:
        ctrl: dict = {}
        for a in actions:
            match a.action:
                case ActionType.MOVE:
                    d = a.direction or "right"
                    ctrl[d] = True
                case ActionType.JUMP:
                    ctrl["jump"] = True
                case ActionType.ATTACK:
                    ctrl["use_item"] = True
                    if a.target and self._mouse_enabled():
                        pyautogui.moveTo(int(a.target[0]), int(a.target[1]))
                case ActionType.USE_ITEM:
                    ctrl["use_item"] = True
                    if a.slot is not None:
                        ctrl["selected_slot"] = a.slot
                case ActionType.SWITCH_SLOT:
                    if a.slot is not None:
                        ctrl["selected_slot"] = a.slot
                case ActionType.PLACE_BLOCK:
                    ctrl["use_item"] = True
                case ActionType.INTERACT:
                    ctrl["right"] = ctrl.get("right", False)
                case ActionType.KEY_PRESS:
                    if a.item == "smart_cursor":
                        ctrl["smart_cursor"] = True
                case ActionType.LOOT_ALL:
                    self._http_fire(_LOOT_ALL_URL)
                case ActionType.QUICK_HEAL:
                    self._http_fire(_QUICK_HEAL_URL)
                case ActionType.PICK_UP | ActionType.CRAFT | ActionType.NONE:
                    pass

        if ctrl:
            self._post_control(ctrl)

    def release_all(self) -> None:
        self._post_control({})

    def _post_control(self, ctrl: dict) -> None:
        try:
            data = json.dumps(ctrl).encode()
            req = urllib.request.Request(_CONTROL_URL, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            with _OPENER.open(req, timeout=0.2) as resp:
                resp.read()
        except Exception:
            pass

    def _http_fire(self, url: str) -> None:
        try:
            with _OPENER.open(url, timeout=0.5) as resp:
                resp.read()
        except Exception:
            pass
