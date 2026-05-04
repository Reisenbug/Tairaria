import sys, os, time, json, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient, scan_skyline
from terraria_agent.hand.mod_controller import ModController
from terraria_agent.terrain_astar import astar
from terraria_agent.agent import _load_skill_frames, _mirror_frame
from terraria_agent.cerebellum.terra_blind_client import _jump_peak_tiles

perception = TerraBlindClient()
controller = ModController()
_BASE = "http://127.0.0.1:17878"

def _post(path, data):
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(_BASE + path, data=body, method="POST")
        urllib.request.urlopen(req, timeout=1)
    except Exception:
        pass

direction = "left"
sign = 1 if direction == "right" else -1

nav_state = "idle"
target_wx = None
target_wy = None
current_action = None
walk_start_y = None
last_sample_t = time.time()
last_sample_pcx = None
stall_count = 0

_STALL_SAMPLE_SEC = 1.0
_STALL_LIMIT = 3
_DEVIATE_Y = 8

def _next_segment(path, idx):
    wx, wy, edge = path[idx]
    action = edge.action
    if action == "walk":
        state = "walk"
    elif action == "jump":
        state = "jump"
    elif action in ("pillar", "pillar_bridge"):
        state = "stop"
    elif action == "bridge":
        state = "bridge"
    else:
        state = "walk"
    return wx, wy, action, state

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
                print(f"[stall] pos=({pcx},{feet_y}) overhead={overhead} blocked_fwd={blocked_fwd} in_pit={in_pit}")
                controller._post_control({})
                nav_state = "idle"
                stall_count = 0
        else:
            stall_count = 0
        last_sample_pcx = pcx
        last_sample_t = now

    head_y = int(p.pos[1] / 16.0)
    skyline = scan_skyline(tw)
    sky_y = skyline.get(pcx)
    overhead = any(
        tw.tile_at(pcx + c, head_y - dy) is not None and tw.tile_at(pcx + c, head_y - dy).solid
        for c in range(2) for dy in range(1, 8)
    )
    blocked_fwd = any(
        tw.tile_at(pcx + sign, feet_y - dy) is not None and tw.tile_at(pcx + sign, feet_y - dy).solid
        for dy in range(1, 4)
    )
    in_pit = sky_y is not None and feet_y > sky_y + 4
    if overhead or in_pit or blocked_fwd:
        controller._post_control({"left" if direction == "right" else "right": True})
        nav_state = "idle"
        continue

    if nav_state == "idle":
        path = astar(state, sign)
        if path is None or not path:
            time.sleep(0.5)
            continue

        # for pwx, pwy, pedge in path:
        #     if pedge.action in ("bridge", "pillar_bridge"):
        #         src_wx = pwx - pedge.dx
        #         src_wy = pwy + pedge.dy
        #         print(f"[bridge] pos=({pcx},{feet_y}) action={pedge.action} reason={pedge.reason!r}")
        #         print(f"[bridge] src=({src_wx},{src_wy}) dst=({pwx},{pwy}) dx={pedge.dx} dy={pedge.dy}")
        #         controller._post_control({})
        #         import sys; sys.exit(0)

        _post("/path_vis", [[pcx, feet_y]] + [[wx, wy] for wx, wy, _ in path])
        print(f"[plan] pos=({pcx},{feet_y}) → path[0]=({path[0][0]},{path[0][1]}) {path[0][2].action}")
        target_wx, target_wy, current_action, nav_state = _next_segment(path, 0)
        walk_start_y = feet_y if nav_state == "walk" else None
        stall_count = 0

    elif nav_state == "walk":
        if walk_start_y is not None and feet_y > walk_start_y + _DEVIATE_Y:
            print(f"[deviate] fell off path feet_y={feet_y} start_y={walk_start_y}, reset")
            controller._post_control({})
            nav_state = "idle"
        elif (target_wx - pcx) * sign <= 0:
            nav_state = "idle"
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
        else:
            frames = _load_skill_frames("bridge_right_2")
            if direction == "left":
                frames = [_mirror_frame(f) for f in frames]
            controller.replay_skill(frames)
            time.sleep(len(frames) / 60.0)

    elif nav_state == "jump":
        head_y = int(p.pos[1] / 16.0)
        overhead_blocked = any(
            tw.tile_at(pcx + col, head_y - dy) is not None and
            tw.tile_at(pcx + col, head_y - dy).solid
            for col in range(2) for dy in range(1, 8)
        )
        if overhead_blocked:
            controller._post_control({"left" if direction == "right" else "right": True})
        else:
            jump_frames = [{"jump": True, direction: True}] * 15 + [{direction: True}] * 30
            controller.replay_skill(jump_frames)
            time.sleep(45 / 60.0)
            nav_state = "idle"
