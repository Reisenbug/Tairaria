import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient, scan_skyline
from terraria_agent.hand.mod_controller import ModController
from terraria_agent.terrain_astar import astar
from terraria_agent.agent import _load_skill_frames, _mirror_frame
from terraria_agent.cerebellum.terra_blind_client import _jump_peak_tiles

perception = TerraBlindClient()
controller = ModController()

direction = "left"
sign = 1 if direction == "right" else -1

nav_state = "idle"
target_wx = None
target_wy = None
current_action = None
last_sample_t = time.time()
last_sample_pcx = None
stall_count = 0
full_path = []
segment_index = 0

_STALL_SAMPLE_SEC = 1.0
_STALL_LIMIT = 3
_PAUSE_SEC = 2.0

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

    now = time.time()
    if now - last_sample_t >= _STALL_SAMPLE_SEC:
        if nav_state != "idle" and last_sample_pcx == pcx:
            stall_count += 1
            if stall_count >= _STALL_LIMIT:
                skyline = scan_skyline(tw)
                print(f"[stall] pos=({pcx},{feet_y}) target=({target_wx},{target_wy}) state={nav_state} action={current_action}")
                print(f"[stall] in_skyline={pcx in skyline} skyline_y={skyline.get(pcx)}")
                print(f"[stall] vx={p.velocity[0]:.2f} vy={p.velocity[1]:.2f}")
                remaining = full_path[segment_index:]
                print(f"[stall] remaining path: {[(wx,wy,e.action) for wx,wy,e in remaining]}")
                controller._post_control({})
                nav_state = "idle"
                stall_count = 0
        else:
            stall_count = 0
        last_sample_pcx = pcx
        last_sample_t = now

    if nav_state == "idle":
        path = astar(state, sign)
        if path is None:
            print("[astar] living tree, pausing")
            time.sleep(0.5)
            continue
        if not path:
            print(f"[astar] no path from ({pcx},{feet_y})")
            time.sleep(0.5)
            continue

        full_path = path
        segment_index = 0
        wx, wy, edge = path[0]
        target_wx, target_wy = wx, wy
        current_action = edge.action
        stall_count = 0
        print(f"[astar] pos=({pcx},{feet_y}) path:")
        for pwx, pwy, pedge in path:
            print(f"  ({pwx},{pwy}) {pedge.action} dx={pedge.dx} dy={pedge.dy}")
        print(f"[astar] → ({wx},{wy}) {edge.action}")

        if current_action == "walk":
            nav_state = "walk"
        elif current_action == "jump":
            nav_state = "jump"
        elif current_action in ("pillar", "pillar_bridge"):
            nav_state = "stop"
        elif current_action == "bridge":
            nav_state = "bridge"

    elif nav_state == "walk":
        dx = (target_wx - pcx) * sign
        if dx <= 0:
            segment_index += 1
            if segment_index >= len(full_path):
                print(f"[astar] path done at ({pcx},{feet_y}), pausing {_PAUSE_SEC}s")
                controller._post_control({})
                time.sleep(_PAUSE_SEC)
                nav_state = "idle"
            else:
                wx, wy, edge = full_path[segment_index]
                target_wx, target_wy = wx, wy
                current_action = edge.action
                print(f"[astar] → ({wx},{wy}) {edge.action}")
                if current_action == "walk":
                    nav_state = "walk"
                elif current_action == "jump":
                    nav_state = "jump"
                elif current_action in ("pillar", "pillar_bridge"):
                    nav_state = "stop"
                elif current_action == "bridge":
                    nav_state = "bridge"
        else:
            controller._post_control({direction: True})

    elif nav_state == "stop":
        if abs(p.velocity[0]) < 0.5:
            nav_state = "pillar"
        else:
            controller._post_control({})

    elif nav_state == "pillar":
        jump_peak = _jump_peak_tiles(state.movement)
        rise = feet_y - target_wy
        if rise <= jump_peak:
            nav_state = "bridge" if current_action == "pillar_bridge" else "jump"
            print(f"[astar] pillar done → {nav_state}")
        else:
            frames = _load_skill_frames("pillar_jump_2_height")
            if direction == "left":
                frames = [_mirror_frame(f) for f in frames]
            controller.replay_skill(frames)
            time.sleep(len(frames) / 60.0)

    elif nav_state == "bridge":
        dx = (target_wx - pcx) * sign
        if dx <= 3:
            nav_state = "jump"
            print("[astar] bridge done → jump")
        else:
            frames = _load_skill_frames("bridge_right_2")
            if direction == "left":
                frames = [_mirror_frame(f) for f in frames]
            controller.replay_skill(frames)
            time.sleep(len(frames) / 60.0)

    elif nav_state == "jump":
        jump_frames = [{"jump": True, direction: True}] * 15 + [{direction: True}] * 30
        controller.replay_skill(jump_frames)
        time.sleep(45 / 60.0)
        segment_index += 1
        if segment_index >= len(full_path):
            print(f"[astar] path done at ({pcx},{feet_y}), pausing {_PAUSE_SEC}s")
            controller._post_control({})
            time.sleep(_PAUSE_SEC)
            nav_state = "idle"
        else:
            wx, wy, edge = full_path[segment_index]
            target_wx, target_wy = wx, wy
            current_action = edge.action
            print(f"[astar] → ({wx},{wy}) {edge.action}")
            if current_action == "walk":
                nav_state = "walk"
            elif current_action == "jump":
                nav_state = "jump"
            elif current_action in ("pillar", "pillar_bridge"):
                nav_state = "stop"
            elif current_action == "bridge":
                nav_state = "bridge"
