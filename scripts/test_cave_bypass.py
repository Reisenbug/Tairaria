import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv()

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient
from terraria_agent.hand.mod_controller import ModController
from terraria_agent.models.actions import ActionType, GameAction
from terraria_agent.cave_detector import _has_overhead, _roof_thickness, detect as cave_detect

perception = TerraBlindClient()
controller = ModController()

print("向右探索，检测到山洞自动触发 cave_bypass，ctrl+c 退出")

current_ctrl = {"right": True}
cave_triggered = False

while True:
    state = perception.detect(frame=None)
    if state.player.hp == 0:
        time.sleep(0.5)
        continue

    tw = state.tile_window
    p = state.player
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    head_y = int(p.pos[1] / 16.0)

    overhead = tw is not None and _has_overhead(tw, pcx, head_y)
    if overhead and tw is not None:
        sign = 1 if p.direction == "right" else -1
        thicknesses = [_roof_thickness(tw, pcx + sign * i, head_y) for i in range(1, 16)]
        print(f"overhead=True thicknesses={thicknesses}")

    if not cave_triggered:
        cave = cave_detect(state)
        if cave:
            _, cave_dir, walk_back, rise_tiles = cave
            print(f"[cave] dir={cave_dir} walk_back={walk_back} rise_tiles={rise_tiles} → 触发")
            controller.release_all()
            controller.fire_skill("cave_bypass", cave_dir, rise_tiles=rise_tiles, walk_back=walk_back)
            cave_triggered = True
            current_ctrl = {}
        elif overhead:
            print(f"overhead=True 但未检测到洞穴")

    if cave_triggered:
        print(f"pos=({p.pos[0]:.1f},{p.pos[1]:.1f}) vel=({p.velocity[0]:.2f},{p.velocity[1]:.2f}) tile=({int(p.pos[0]/16)},{int(p.pos[1]/16)})")

    if current_ctrl:
        actions = [GameAction(action=ActionType.MOVE, direction="right")]
    else:
        actions = [GameAction(action=ActionType.NONE)]
    controller.execute(actions)

    time.sleep(0.2)
