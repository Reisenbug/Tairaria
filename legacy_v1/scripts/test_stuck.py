import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient
from terraria_agent.hand.mod_controller import ModController
from terraria_agent.agent import TriggerDetector, _overhead_shallow, _handle_stuck

perception = TerraBlindClient()
controller = ModController()
trigger = TriggerDetector()

current_ctrl = {"right": True}

print("向右走，检测卡住，ctrl+c 退出")

while True:
    now = time.time()
    state = perception.detect(frame=None)
    p = state.player

    controller._post_control(current_ctrl)

    reason = trigger.check(state, current_ctrl, now)
    shallow = _overhead_shallow(state)
    print(f"  pos={p.pos[0]/16:.1f}t  reason={reason or '-'}  shallow={shallow}")

    if reason == "卡住":
        print(f"[STUCK] pos=({p.pos[0]/16:.1f}, {p.pos[1]/16:.1f})t  shallow={shallow}")
        _handle_stuck(state, controller, perception, [False])
        current_ctrl = {"right": True}

    time.sleep(0.2)
