from __future__ import annotations

import json
import urllib.request

from terraria_agent.models.actions import ActionType, GameAction

_CONTROL_URL = "http://127.0.0.1:17878/control"
_NO_PROXY_HANDLER = urllib.request.ProxyHandler({})
_OPENER = urllib.request.build_opener(_NO_PROXY_HANDLER)

_QUICK_HEAL_URL = "http://127.0.0.1:17878/quick_heal"
_LOOT_ALL_URL = "http://127.0.0.1:17878/loot_all"
_INTERACT_URL = "http://127.0.0.1:17878/interact"
_PLACE_URL = "http://127.0.0.1:17878/place"
_PLACE_STOP_URL = "http://127.0.0.1:17878/place_stop"
_SKILL_URL = "http://127.0.0.1:17878/skill"
_WALK_TO_EDGE_URL = "http://127.0.0.1:17878/walk_to_edge"
_REPLAY_URL = "http://127.0.0.1:17878/replay"
_FIGHT_URL = "http://127.0.0.1:17878/fight"


class ModController:
    def __init__(self, mouse_control_flag=None):
        pass

    def execute(self, actions: list[GameAction]) -> None:
        ctrl: dict = {}
        for a in actions:
            match a.action:
                case ActionType.MOVE:
                    ctrl[a.direction or "right"] = True
                case ActionType.JUMP:
                    ctrl["jump"] = True
                case ActionType.ATTACK:
                    ctrl["use_item"] = True
                case ActionType.USE_ITEM_MOD:
                    ctrl["use_item"] = True
                    if a.mx is not None:
                        ctrl["mx"] = a.mx
                    if a.my is not None:
                        ctrl["my"] = a.my
                case ActionType.USE_ITEM:
                    ctrl["use_item"] = True
                    if a.slot is not None:
                        ctrl["selected_slot"] = a.slot
                case ActionType.SWITCH_SLOT:
                    if a.slot is not None:
                        ctrl["selected_slot"] = a.slot
                case ActionType.PLACE_BLOCK:
                    ctrl["use_item"] = True
                case ActionType.INTERACT_MOD:
                    ctrl["use_tile"] = True
                    if a.mx is not None:
                        ctrl["mx"] = a.mx
                    if a.my is not None:
                        ctrl["my"] = a.my
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

        self._post_control(ctrl)

    def fight_start(self, max_dist: float = 20.0) -> None:
        self._http_post_json(_FIGHT_URL, {"active": True, "max_dist": max_dist})

    def fight_stop(self) -> None:
        self._http_post_json(_FIGHT_URL, {"active": False})

    def walk_to_edge(self, direction: str, extra_tiles: float = 0.5) -> None:
        self._http_post_json(_WALK_TO_EDGE_URL, {"direction": direction, "extra_tiles": extra_tiles})

    def replay_skill(self, frames: list) -> None:
        self._http_post_json(_REPLAY_URL, frames)

    def fire_skill(self, name: str, direction: str = "right", rise_tiles: int = 8, walk_back: int = 2) -> None:
        self._http_post_json(_SKILL_URL, {"name": name, "direction": direction, "rise_tiles": rise_tiles, "walk_back": walk_back})

    def release_all(self) -> None:
        self._post_control({})

    def _post_control(self, ctrl: dict) -> None:
        self._http_post_json(_CONTROL_URL, ctrl)

    def _http_post_json(self, url: str, payload) -> None:
        from terraria_agent.diag_log import diag
        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            with _OPENER.open(req, timeout=0.2) as resp:
                resp.read()
        except Exception as e:
            diag("http_post", f"FAIL url={url} err={type(e).__name__}:{e}")

    def _http_fire(self, url: str) -> None:
        try:
            with _OPENER.open(url, timeout=0.5) as resp:
                resp.read()
        except Exception:
            pass
