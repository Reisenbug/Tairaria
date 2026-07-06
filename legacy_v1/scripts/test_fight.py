import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv()

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient
from terraria_agent.hand.mod_controller import ModController

perception = TerraBlindClient()
controller = ModController()

print("mod端自动攻击最近敌人（5秒超时），ctrl+c 退出")

fighting = False

try:
    while True:
        state = perception.detect(frame=None)
        if state is None or state.player.hp == 0:
            time.sleep(0.2)
            continue

        if state.enemies:
            nearest = min(state.enemies, key=lambda e: e.distance)
            print(f"{nearest.type} hp={nearest.hp}/{nearest.max_hp} dist={nearest.distance:.1f}")
            if not fighting:
                controller.fight_start(max_dist=20.0)
                fighting = True
        else:
            if fighting:
                controller.fight_stop()
                fighting = False
            print("没有敌人", end="\r")

        time.sleep(0.2)
finally:
    controller.fight_stop()
