import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv()

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient
from terraria_agent.hand.mod_controller import ModController
from terraria_agent.models.actions import ActionType, GameAction

perception = TerraBlindClient()
controller = ModController()

print("自动攻击最近敌人，ctrl+c 退出")

while True:
    state = perception.detect(frame=None)
    if state is None or state.player.hp == 0:
        time.sleep(0.2)
        continue

    if not state.enemies:
        controller.release_all()
        print("没有敌人", end="\r")
        time.sleep(0.2)
        continue

    nearest = min(state.enemies, key=lambda e: e.distance)
    p = state.player
    pcx = p.pos[0] + p.width / 2.0
    pcy = p.pos[1] + p.height / 2.0
    ncx = nearest.pos[0] + nearest.width / 2.0
    ncy = nearest.pos[1] + nearest.height / 2.0
    mx = (ncx - pcx) / 16.0
    my = (ncy - pcy) / 16.0
    print(f"{nearest.type} hp={nearest.hp}/{nearest.max_hp} dist={nearest.distance:.1f} mx={mx:.1f} my={my:.1f}")
    controller.execute([GameAction(action=ActionType.USE_ITEM_MOD, mx=mx, my=my)])
    time.sleep(0.1)
