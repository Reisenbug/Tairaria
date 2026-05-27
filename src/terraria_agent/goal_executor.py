from __future__ import annotations

import time
from typing import Callable

from terraria_agent.models.game_state import GameState
from terraria_agent.hand.mod_controller import ModController
from terraria_agent.models.actions import ActionType, GameAction
from terraria_agent.cerebellum.nav_client import NavClient

_TILE = 16.0
_ARRIVE_DIST = 3.0


class GoalExecutor:
    def __init__(self, controller: ModController) -> None:
        self._ctrl = controller
        self._nav = NavClient()
        self._goal: str | None = None
        self._target_type: str | None = None
        self._target_abs_x: float | None = None
        self._deadline: float = 0.0
        self._on_done: Callable[[str], None] | None = None
        self._phase: str = ""
        # tile the current nav was launched toward; None means we haven't started yet
        self._nav_target: tuple[int, int] | None = None

    @property
    def active(self) -> bool:
        return self._goal is not None

    def start(self, goal: str, target: dict, timeout: float, on_done: Callable[[str], None]) -> None:
        self._goal = goal
        self._target_type = target.get("type")
        self._target_abs_x = None
        self._deadline = time.time() + timeout
        self._on_done = on_done
        self._phase = "navigate"
        self._nav_target = None
        print(f"[goal] 开始 {goal} target={target} timeout={timeout}s")

    def cancel(self) -> None:
        self._nav.stop()
        self._nav_target = None
        self._goal = None
        self._phase = ""
        self._ctrl.release_all()

    def tick(self, state: GameState) -> dict:
        if not self._goal:
            return {}

        if time.time() >= self._deadline:
            print(f"[goal] {self._goal} 超时")
            self._finish("timeout")
            return {}

        if self._goal == "open_chest":
            return self._tick_open_chest(state)
        elif self._goal == "chop_tree":
            return self._tick_chop_tree(state)

        return {}

    def _tick_open_chest(self, state: GameState) -> dict:
        if self._phase == "looting":
            if not state.chest_open:
                print("[goal] open_chest 完成（loot 结束）")
                self._finish("done")
                return {}
            self._ctrl._http_fire("http://127.0.0.1:17878/loot_all")
            return {}

        if self._phase == "opening":
            if state.chest_open:
                print("[goal] 箱子已开，开始 loot")
                self._phase = "looting"
                return {}
            obj = self._find_nearest("chest", state)
            if obj is None:
                self._finish("not_found")
                return {}
            return self._aim_and_interact(obj, state)

        # navigate
        obj = self._find_nearest("chest", state)
        if obj is None:
            self._finish("not_found")
            return {}
        if self._target_abs_x is None:
            self._target_abs_x = obj.pos[0]

        if self._dist_to(obj, state) <= _ARRIVE_DIST:
            self._nav.stop()
            self._phase = "opening"
            return self._aim_and_interact(obj, state)
        return self._navigate_to_obj(obj, state)

    def _tick_chop_tree(self, state: GameState) -> dict:
        if self._phase == "looting_drops":
            self._loot_ticks = getattr(self, "_loot_ticks", 0) + 1
            self._ctrl._http_fire("http://127.0.0.1:17878/loot_all")
            if self._loot_ticks >= 5:
                print("[goal] chop_tree 完成（loot 结束）")
                self._finish("done")
            return {}

        obj = self._find_nearest("tree", state, min_height=15)
        if obj is None:
            if self._phase == "chopping":
                print("[goal] 树消失，开始捡掉落物")
                self._phase = "looting_drops"
                self._loot_ticks = 0
                return {}
            self._finish("not_found")
            return {}
        if self._target_abs_x is None:
            self._target_abs_x = obj.pos[0]

        if self._dist_to(obj, state) <= _ARRIVE_DIST:
            self._nav.stop()
            self._phase = "chopping"
            axe_slot = next((s.slot_index for s in state.inventory_slots[:10] if s.is_axe), None)
            p = state.player
            pcx = p.pos[0] + p.width / 2.0
            pcy = p.pos[1] + p.height / 2.0
            tcx = obj.pos[0] + _TILE
            tcy = obj.pos[1] + obj.height * _TILE
            mx = (tcx - pcx) / _TILE
            my = (tcy - pcy) / _TILE
            ctrl = {"use_item": True, "sc": 1, "mx": mx, "my": my}
            if axe_slot is not None:
                ctrl["selected_slot"] = axe_slot
            return ctrl
        return self._navigate_to_obj(obj, state)

    def _find_nearest(self, obj_type: str, state: GameState, min_height: int = 0):
        candidates = [o for o in state.objects if o.type == obj_type and o.height >= min_height]
        if not candidates:
            return None
        if self._target_abs_x is not None:
            anchored = [o for o in candidates if abs(o.pos[0] - self._target_abs_x) < _TILE * 3]
            if anchored:
                return min(anchored, key=lambda o: o.distance)
            return None
        return min(candidates, key=lambda o: o.distance)

    def _dist_to(self, obj, state: GameState) -> float:
        p = state.player
        pcx = p.pos[0] + p.width / 2.0
        tcx = obj.pos[0] + _TILE
        return abs(pcx - tcx) / _TILE

    def _navigate_to_obj(self, obj, state: GameState) -> dict:
        # tile-space goal: aim at the tile next to the object so we arrive within reach
        gx = int((obj.pos[0] + _TILE) / _TILE)
        p = state.player
        gy = int((p.pos[1] + p.height) / _TILE)
        pcx = int((p.pos[0] + p.width / 2.0) / _TILE)
        pcy = int((p.pos[1] + p.height) / _TILE)

        # (re)start if the target moved enough or we don't have a nav running
        if self._nav_target is None or abs(self._nav_target[0] - gx) > 1:
            r = self._nav.start(gx, gy, player_tile=(pcx, pcy))
            self._nav_target = (gx, gy)
            if r.status == "failed":
                print(f"[goal] nav 启动失败: {r.reason} ({r.human})")
                self._finish(f"nav_failed:{r.reason}")
                return {}
            return {}

        r = self._nav.poll()
        if r.status == "running":
            return {}
        if r.status == "done":
            return {}
        # failed
        print(f"[goal] nav {r.reason}: {r.human} (elapsed={r.elapsed_sec:.1f}s)")
        self._nav_target = None
        self._finish(f"nav_failed:{r.reason}")
        return {}

    def _aim_and_interact(self, obj, state: GameState) -> dict:
        p = state.player
        pcx = p.pos[0] + p.width / 2.0
        pcy = p.pos[1] + p.height / 2.0
        tcx = obj.pos[0] + _TILE
        tcy = obj.pos[1] + _TILE
        mx = (tcx - pcx) / _TILE
        my = (tcy - pcy) / _TILE
        self._ctrl.execute([GameAction(action=ActionType.INTERACT_MOD, mx=mx, my=my)])
        return {}

    def _finish(self, reason: str) -> None:
        goal = self._goal
        self._goal = None
        self._phase = ""
        self._nav.stop()
        self._nav_target = None
        self._ctrl.release_all()
        if self._on_done:
            self._on_done(f"{goal}:{reason}")
