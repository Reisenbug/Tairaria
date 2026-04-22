from __future__ import annotations

import json
import time
import threading
import urllib.request

from dotenv import load_dotenv
load_dotenv()

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient
from terraria_agent.llm_client import LLMClient
from terraria_agent.state_serializer import serialize

_CONTROL_URL = "http://127.0.0.1:17878/control"
_NO_PROXY = urllib.request.ProxyHandler({})
_OPENER = urllib.request.build_opener(_NO_PROXY)

_EXEC_TICK = 0.2


def _post_control(ctrl: dict) -> None:
    data = json.dumps(ctrl).encode()
    req = urllib.request.Request(_CONTROL_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with _OPENER.open(req, timeout=0.5) as resp:
            resp.read()
    except Exception as e:
        print(f"[control] POST failed: {e}")


def _safety_interrupt(state) -> str | None:
    if state.player.hp < state.player.max_hp * 0.3:
        return "血量低"
    return None


def run() -> None:
    perception = TerraBlindClient()
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

        if time.time() >= deadline or (llm_thread is None or not llm_thread.is_alive()):
            if llm_thread is None or not llm_thread.is_alive():
                state_text = serialize(state)
                print(f"\n[状态]\n{state_text}")
                llm_thread = threading.Thread(target=llm_worker, args=(state_text,), daemon=True)
                llm_thread.start()

        if current_ctrl:
            _post_control(current_ctrl)

        time.sleep(_EXEC_TICK)


if __name__ == "__main__":
    run()
