import sys, os, time, json, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient, _jump_envelope
from terraria_agent.models.game_state import MovementInfo
from terraria_agent.terrain_astar2 import (
    astar2, _solid, _standable, _dist_to_ground, _step_cost,
    _GROUND_MOVEMENT, _GOAL_RANGE, _MAX_BRIDGE,
)

perception = TerraBlindClient()
_BASE = "http://127.0.0.1:17878"
direction = "left"
sign = 1 if direction == "right" else -1


def _post(path, data):
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(_BASE + path, data=body, method="POST")
        urllib.request.urlopen(req, timeout=1)
    except Exception:
        pass


while True:
    state = perception.detect(frame=None)
    if state.player.hp == 0:
        time.sleep(0.2)
        continue
    tw = state.tile_window
    if tw is None:
        time.sleep(0.2)
        continue

    p = state.player
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    feet_y = int((p.pos[1] + p.height) / 16.0)

    t0 = time.time()
    result = astar2(state, sign)
    dt = time.time() - t0
    print(f"[time] astar2 {dt*1000:.0f}ms")
    if result:
        for wx, wy, action in result[0]:
            if action == "bridge":
                print(f"  [bridge] ({wx},{wy}) from_y={wy}")

    if not result:
        print(f"[vis] no path at ({pcx},{feet_y})")
        time.sleep(2.0)
        continue
    path, total_cost = result
    if not path:
        time.sleep(2.0)
        continue
    else:
        print(f"[path] ({pcx},{feet_y})→({path[-1][0]},{path[-1][1]}) len={len(path)} cost={total_cost:.1f}")
        tiles = [{"wx": pcx, "wy": feet_y, "r": 255, "g": 255, "b": 255}]
        labels = [{"wx": path[-1][0], "wy": path[-1][1],
                   "text": f"goal len={len(path)} cost={total_cost:.1f}",
                   "r": 255, "g": 200, "b": 0}]
        prev_wx, prev_y = pcx, feet_y
        prev_action = None
        rise_run = 0
        rise_start_y = feet_y
        rise_x = pcx
        for wx, wy, action in path:
            if action == "bridge":
                adx = abs(wx - prev_wx)
                dy_per_step = (wy - prev_y) / max(adx, 1)
                for i, bx in enumerate(range(prev_wx + sign, wx, sign)):
                    by = int(prev_y + dy_per_step * (i + 1))
                    tiles.append({"wx": bx, "wy": by, "r": 180, "g": 0, "b": 255})
            elif action == "jump":
                adx = abs(wx - prev_wx)
                js = 1 if wx > prev_wx else -1
                envelope = _jump_envelope(_GROUND_MOVEMENT, max_cols=adx + 1)
                for i in range(adx + 1):
                    bx = prev_wx + js * i
                    by = prev_y + envelope[i]
                    tiles.append({"wx": bx, "wy": by, "r": 100, "g": 255, "b": 100})
                arc_end_y = prev_y + envelope[adx]
                for y in range(arc_end_y, wy):
                    tiles.append({"wx": wx, "wy": y, "r": 100, "g": 255, "b": 100})
            node_color = (255, 80, 80) if action == "pillar" else (255, 200, 0) if action == "jump" else (180, 0, 255) if action == "bridge" else (100, 220, 255)
            tiles.append({"wx": wx, "wy": wy, "r": node_color[0], "g": node_color[1], "b": node_color[2]})
            if wy > prev_y and action not in ("bridge", "jump"):
                for y in range(prev_y, wy):
                    tiles.append({"wx": wx, "wy": y, "r": 255, "g": 140, "b": 0})
                if rise_run > 0:
                    c = (255, 80, 80) if rise_run > 7 else (100, 255, 100)
                    labels.append({"wx": rise_x, "wy": rise_start_y - rise_run,
                                   "text": f"pillar {rise_run}" if rise_run > 7 else f"rise {rise_run}",
                                   "r": c[0], "g": c[1], "b": c[2]})
                    rise_run = 0
            elif wy < prev_y and action not in ("bridge", "jump"):
                if rise_run == 0:
                    rise_start_y = prev_y
                    rise_x = wx
                rise_run += 1
            else:
                if rise_run > 0:
                    c = (255, 80, 80) if rise_run > 7 else (100, 255, 100)
                    labels.append({"wx": rise_x, "wy": rise_start_y - rise_run,
                                   "text": f"pillar {rise_run}" if rise_run > 7 else f"rise {rise_run}",
                                   "r": c[0], "g": c[1], "b": c[2]})
                    rise_run = 0
            prev_wx, prev_y = wx, wy
            prev_action = action
        if rise_run > 0:
            c = (255, 80, 80) if rise_run > 7 else (100, 255, 100)
            labels.append({"wx": rise_x, "wy": rise_start_y - rise_run,
                           "text": f"pillar {rise_run}" if rise_run > 7 else f"rise {rise_run}",
                           "r": c[0], "g": c[1], "b": c[2]})
        _post("/path_vis_tiles", tiles)
        _post("/debug_labels", labels)

    time.sleep(2.0)
