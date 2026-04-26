from __future__ import annotations

import json
import urllib.request

import pyautogui

from terraria_agent.hand.key_state import KeyState
from terraria_agent.models.actions import ActionType, GameAction

pyautogui.PAUSE = 0.0
pyautogui.FAILSAFE = False

_SW, _SH = pyautogui.size()
_MARGIN = 50

_CONTROL_URL = "http://127.0.0.1:17878/control"
_NO_PROXY_HANDLER = urllib.request.ProxyHandler({})
_OPENER = urllib.request.build_opener(_NO_PROXY_HANDLER)

_QUICK_HEAL_URL = "http://127.0.0.1:17878/quick_heal"
_LOOT_ALL_URL = "http://127.0.0.1:17878/loot_all"
_INTERACT_URL = "http://127.0.0.1:17878/interact"
_PLACE_URL = "http://127.0.0.1:17878/place"
_PLACE_STOP_URL = "http://127.0.0.1:17878/place_stop"
_SKILL_URL = "http://127.0.0.1:17878/skill"


class ModController:
    def __init__(self, mouse_control_flag=None):
        self.key_state = KeyState()
        self._mouse_enabled = mouse_control_flag or (lambda: True)
        self._mouse_paused = False

    def toggle_mouse(self) -> bool:
        self._mouse_paused = not self._mouse_paused
        if self._mouse_paused:
            if getattr(self, "_holding_mouse", False):
                pyautogui.mouseUp(button="left")
                self._holding_mouse = False
        return self._mouse_paused

    def execute(self, actions: list[GameAction]) -> None:
        ctrl: dict = {}
        need_mouse_down = False
        for a in actions:
            match a.action:
                case ActionType.MOVE:
                    d = a.direction or "right"
                    ctrl[d] = True
                case ActionType.JUMP:
                    ctrl["jump"] = True
                case ActionType.ATTACK:
                    need_mouse_down = True
                    if a.target and self._mouse_enabled() and not self._mouse_paused:
                        raw_x, raw_y = int(a.target[0]), int(a.target[1])
                        x = max(_MARGIN, min(raw_x, _SW - _MARGIN))
                        y = max(_MARGIN, min(raw_y, _SH - _MARGIN))
                        print(f"[mouse] raw=({raw_x},{raw_y}) clamped=({x},{y}) screen=({_SW},{_SH})")
                        if x != _MARGIN and y != _MARGIN:
                            pyautogui.moveTo(x, y)
                case ActionType.USE_ITEM:
                    need_mouse_down = True
                    if a.slot is not None:
                        ctrl["selected_slot"] = a.slot
                case ActionType.SWITCH_SLOT:
                    if a.slot is not None:
                        ctrl["selected_slot"] = a.slot
                case ActionType.PLACE_BLOCK:
                    need_mouse_down = True
                case ActionType.INTERACT:
                    if a.tile is not None:
                        self._http_post_json(_INTERACT_URL, {"tile_x": int(a.tile[0]), "tile_y": int(a.tile[1])})
                case ActionType.PLACE:
                    if a.dx is not None and a.dy is not None and a.slot is not None and a.duration_frames is not None:
                        self._http_post_json(_PLACE_URL, {
                            "dx": int(a.dx), "dy": int(a.dy), "slot": int(a.slot),
                            "duration_frames": int(a.duration_frames),
                        })
                case ActionType.PLACE_STOP:
                    self._http_fire(_PLACE_STOP_URL)
                case ActionType.LOOT_ALL:
                    self._http_fire(_LOOT_ALL_URL)
                case ActionType.QUICK_HEAL:
                    self._http_fire(_QUICK_HEAL_URL)
                case ActionType.PICK_UP | ActionType.CRAFT | ActionType.NONE:
                    pass

        if need_mouse_down and self._mouse_enabled() and not self._mouse_paused:
            if not self.key_state.press("mouse:left"):
                pass
            pyautogui.mouseDown(button="left")
            self._holding_mouse = True
        elif getattr(self, "_holding_mouse", False):
            pyautogui.mouseUp(button="left")
            self.key_state.release("mouse:left")
            self._holding_mouse = False

        if ctrl:
            self._post_control(ctrl)

    def fire_skill(self, name: str, direction: str = "right", rise_tiles: int = 8, walk_back: int = 2) -> None:
        self._http_post_json(_SKILL_URL, {"name": name, "direction": direction, "rise_tiles": rise_tiles, "walk_back": walk_back})

    def release_all(self) -> None:
        self._post_control({})
        if getattr(self, "_holding_mouse", False):
            pyautogui.mouseUp(button="left")
            self._holding_mouse = False

    def _post_control(self, ctrl: dict) -> None:
        self._http_post_json(_CONTROL_URL, ctrl)

    def _http_post_json(self, url: str, payload: dict) -> None:
        from terraria_agent.diag_log import diag
        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            with _OPENER.open(req, timeout=0.2) as resp:
                resp.read()
        except Exception as e:
            diag("http_post", f"FAIL url={url} payload={payload} err={type(e).__name__}:{e}")

    def _http_fire(self, url: str) -> None:
        try:
            with _OPENER.open(url, timeout=0.5) as resp:
                resp.read()
        except Exception:
            pass
