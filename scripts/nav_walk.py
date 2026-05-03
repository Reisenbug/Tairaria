import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient
from terraria_agent.hand.mod_controller import ModController
from terraria_agent.terrain_nav import Navigator
from terraria_agent.agent import _load_skill_frames

perception = TerraBlindClient()
controller = ModController()
nav = Navigator(controller, _load_skill_frames)
nav.set_direction("right")

while True:
    state = perception.detect(frame=None)
    if state.player.hp == 0:
        time.sleep(0.2)
        continue

    ctrl = nav.tick(state)
    if ctrl is not None:
        controller._post_control(ctrl)

    time.sleep(0.2)
