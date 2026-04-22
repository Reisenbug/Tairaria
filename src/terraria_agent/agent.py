from __future__ import annotations

import time
import threading

from dotenv import load_dotenv
load_dotenv()

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient
from terraria_agent.geometry import player_center_world, world_to_screen
from terraria_agent.hand.mod_controller import ModController
from terraria_agent.llm_client import LLMClient
from terraria_agent.models.actions import ActionType, GameAction
from terraria_agent.models.game_state import Camera, GameState
from terraria_agent.state_serializer import serialize

_EXEC_TICK = 0.2
_TILE = 16.0


def _parse_actions(ctrl: dict, state: GameState) -> list[GameAction]:
    actions: list[GameAction] = []

    if ctrl.get("quick_heal"):
        actions.append(GameAction(action=ActionType.QUICK_HEAL))
        return actions

    if ctrl.get("loot_all"):
        actions.append(GameAction(action=ActionType.LOOT_ALL))

    if ctrl.get("interact"):
        tile_x = ctrl.get("tile_x")
        tile_y = ctrl.get("tile_y")
        if tile_x is not None and tile_y is not None:
            actions.append(GameAction(action=ActionType.INTERACT, tile=(int(tile_x), int(tile_y))))

    if "selected_slot" in ctrl:
        actions.append(GameAction(action=ActionType.SWITCH_SLOT, slot=int(ctrl["selected_slot"])))

    for direction in ("left", "right", "up", "down"):
        if ctrl.get(direction):
            actions.append(GameAction(action=ActionType.MOVE, direction=direction))

    if ctrl.get("jump"):
        actions.append(GameAction(action=ActionType.JUMP))

    if ctrl.get("use_item"):
        rel_x = ctrl.get("mouse_x")
        rel_y = ctrl.get("mouse_y")
        if rel_x is not None and rel_y is not None:
            pcx, pcy = player_center_world(state.player)
            world_xy = (pcx + float(rel_x) * _TILE, pcy + float(rel_y) * _TILE)
            target = world_to_screen(world_xy, state.camera)
        else:
            target = None
        actions.append(GameAction(action=ActionType.ATTACK, target=target))

    if not actions:
        actions.append(GameAction(action=ActionType.NONE))

    return actions


def _safety_interrupt(state) -> str | None:
    if state.player.hp < state.player.max_hp * 0.3:
        return "血量低"
    return None


def run() -> None:
    perception = TerraBlindClient()
    controller = ModController()
    llm = LLMClient()
    print("[agent] 启动 — ctrl+c 停止")

    current_ctrl: dict = {"right": True}
    pending: dict | None = None
    pending_lock = threading.Lock()

    def llm_worker(state_text: str) -> None:
        nonlocal pending
        decision = llm.decide(state_text)
        with pending_lock:
            pending = decision if decision else {}

    llm_thread: threading.Thread | None = None
    deadline: float = 0.0

    while True:
        state = perception.detect(frame=None)
        if state.player.hp == 0:
            print("[agent] 等待游戏状态...")
            time.sleep(2.0)
            continue

        reason = _safety_interrupt(state)
        if reason:
            print(f"[agent] 安全中断: {reason}")
            current_ctrl = {"left": True}
            deadline = time.time() + 3.0

        with pending_lock:
            if pending is not None:
                decision = pending
                pending = None
                thought = decision.get("思考", "")
                ctrl = decision.get("控制", {})
                duration = float(decision.get("持续秒数", 1.0))
                print(f"[决策] 思考={thought!r} 控制={ctrl} 持续={duration}s")
                if ctrl:
                    current_ctrl = ctrl
                    deadline = time.time() + duration

        if llm_thread is None or not llm_thread.is_alive():
            state_text = serialize(state)
            print(f"\n[状态]\n{state_text}")
            llm_thread = threading.Thread(target=llm_worker, args=(state_text,), daemon=True)
            llm_thread.start()

        actions = _parse_actions(current_ctrl, state)
        controller.execute(actions)

        time.sleep(_EXEC_TICK)


if __name__ == "__main__":
    run()
