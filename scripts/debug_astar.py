import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient, scan_skyline
from terraria_agent.terrain_astar import astar

perception = TerraBlindClient()
direction = "right"
sign = 1 if direction == "right" else -1

while True:
    state = perception.detect(frame=None)
    if state.player.hp == 0:
        time.sleep(0.5)
        continue

    tw = state.tile_window
    if tw is None:
        time.sleep(0.5)
        continue

    p = state.player
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    feet_y = int((p.pos[1] + p.height) / 16.0)

    path = astar(state, sign)

    if path is None:
        print(f"[astar] living tree ahead, pausing")
    elif not path:
        print(f"[astar] no path found from ({pcx},{feet_y})")
    else:
        goal_wx, goal_wy, _ = path[-1]
        print(f"\n[astar] pos=({pcx},{feet_y}) goal=({goal_wx},{goal_wy}) steps={len(path)}")
        for wx, wy, edge in path:
            print(f"  → ({wx},{wy}) {edge.action} dx={edge.dx} dy={edge.dy} cost={edge.cost:.1f}")

    time.sleep(2.0)
