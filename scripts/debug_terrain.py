import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv()

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient
from terraria_agent.cerebellum.terra_blind_client import _scan_terrain, _is_standable_at, _TILE_PX

perception = TerraBlindClient()

while True:
    state = perception.detect(frame=None)
    if state is None or state.player.hp == 0:
        time.sleep(0.2)
        continue

    tw = state.tile_window
    p = state.player
    if tw is None:
        print("no tile window")
        time.sleep(0.2)
        continue

    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    feet_y = int((p.pos[1] + p.height) / 16.0)

    # 向右扫60格找坑
    def scan_pits(sign, cols=60):
        pits = []
        in_pit = False
        pit_start = None
        for i in range(1, cols):
            cx = pcx + sign * i
            has_ground = any(_is_standable_at(tw, cx, feet_y + dy) for dy in range(3))
            if not has_ground and not in_pit:
                in_pit = True
                pit_start = i
            elif has_ground and in_pit:
                pits.append((pit_start, i - 1, i - pit_start))
                in_pit = False
        if in_pit:
            pits.append((pit_start, cols, cols - pit_start))
        return pits

    right_pits = scan_pits(+1)
    left_pits  = scan_pits(-1)

    print(f"\rpcx={pcx} feet_y={feet_y} | "
          f"右侧坑:{right_pits} | 左侧坑:{left_pits}    ", end="")
    time.sleep(0.2)
