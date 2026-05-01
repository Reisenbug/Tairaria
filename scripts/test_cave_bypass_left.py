import sys, os, time, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv()

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient
from terraria_agent.hand.mod_controller import ModController
from terraria_agent.models.actions import ActionType, GameAction
from terraria_agent.agent import _cave_bypass_worker
from terraria_agent.cave_detector import detect as cave_detect

perception = TerraBlindClient()
controller = ModController()

print("向左探索，检测到山洞自动触发 cave_bypass_left，ctrl+c 退出")

triggered = False

while True:
    state = perception.detect(frame=None)
    if state is None or state.player.hp == 0:
        time.sleep(0.2)
        continue

    if not triggered:
        cave = cave_detect(state)
        if cave:
            _, cave_dir, _, _ = cave
            print(f"[cave] dir={cave_dir} → 触发 bypass")
            controller.release_all()
            triggered = True
            t = threading.Thread(target=_cave_bypass_worker, args=(controller, cave_dir), daemon=True)
            t.start()
        else:
            controller.execute([GameAction(action=ActionType.MOVE, direction="left")])
    else:
        time.sleep(0.2)
        continue

    time.sleep(0.2)
