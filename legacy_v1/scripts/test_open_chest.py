import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv()

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient
from terraria_agent.hand.mod_controller import ModController
from terraria_agent.models.actions import ActionType, GameAction

perception = TerraBlindClient()
controller = ModController()

print("找最近箱子并右键打开，ctrl+c 退出")

while True:
    state = perception.detect(frame=None)
    if state is None:
        time.sleep(0.2)
        continue

    chests = [o for o in state.objects if o.type == "chest"]
    if not chests:
        print("没有箱子", end="\r")
        time.sleep(0.3)
        continue

    nearest = min(chests, key=lambda o: o.distance)
    p = state.player
    pcx = p.pos[0] + p.width / 2.0
    pcy = p.pos[1] + p.height / 2.0
    tcx = nearest.pos[0] + 16.0
    tcy = nearest.pos[1] + 16.0
    mx = (tcx - pcx) / 16.0
    my = (tcy - pcy) / 16.0
    print(f"箱子 dist={nearest.distance:.1f} mx={mx:.1f} my={my:.1f}")
    controller.execute([GameAction(action=ActionType.INTERACT_MOD, mx=mx, my=my)])
    time.sleep(0.1)
