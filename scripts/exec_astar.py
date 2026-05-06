import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient, _jump_peak_tiles
from terraria_agent.hand.mod_controller import ModController
from terraria_agent.agent import _mirror_frame, _load_skill_frames
from terraria_agent.terrain_astar2 import astar2, _standable

direction = "left"
sign = 1 if direction == "right" else -1

ARRIVE_X = 2
DEVIATE_Y = 10
STALL_LIMIT = 4
REPLAN_INTERVAL = 20.0
PILLAR_THRESH = 5

perception = TerraBlindClient()
controller = ModController()

pillar_frames = _load_skill_frames("pillar_jump_2_height")
if direction == "left":
    pillar_frames = [_mirror_frame(f) for f in pillar_frames]
bridge_frames = _load_skill_frames(f"bridge_{direction}_2")
jump_frames = ([{"jump": True, direction: True}] * 15 +
               [{direction: True}] * 30)


def _player_tile(p):
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    feet_y = int((p.pos[1] + p.height) / 16.0)
    return pcx, feet_y


def _rise_streak_end(path, idx):
    """Return the target wy of the contiguous move/fall streak starting at idx."""
    wy = path[idx][1]
    for i in range(idx, len(path)):
        if path[i][2] not in ("move", "fall"):
            break
        wy = path[i][1]
    return wy


nav_state = "idle"
path_plan = []
path_idx = 0
target_wx = target_wy = target_action = None
seg_start_y = None

last_stall_t = time.time()
last_stall_pcx = None
stall_count = 0
last_replan_t = time.time()


def do_replan(state, reason):
    global nav_state, path_plan, path_idx, target_wx, target_wy, target_action
    global seg_start_y, stall_count, last_replan_t
    print(f"[replan] {reason}")
    controller.release_all()
    result = astar2(state, sign)
    if not result:
        nav_state = "idle"
        path_plan = []
        path_idx = 0
        last_replan_t = time.time()
        return
    path_plan, cost = result
    path_idx = 0
    nav_state = "idle"
    stall_count = 0
    last_replan_t = time.time()
    print(f"[plan] len={len(path_plan)} cost={cost:.1f}")


while True:
    state = perception.detect(frame=None)
    p = state.player
    if p.hp == 0:
        time.sleep(0.2)
        continue
    if state.tile_window is None:
        time.sleep(0.1)
        continue

    pcx, feet_y = _player_tile(p)
    now = time.time()

    # stall detection
    if now - last_stall_t >= 1.0:
        if nav_state != "idle" and last_stall_pcx == pcx:
            stall_count += 1
            if stall_count >= STALL_LIMIT:
                do_replan(state, f"stall at x={pcx}")
                time.sleep(0.1)
                continue
        else:
            stall_count = 0
        last_stall_pcx = pcx
        last_stall_t = now

    # periodic replan
    if nav_state == "move" and now - last_replan_t > REPLAN_INTERVAL:
        do_replan(state, "periodic")
        time.sleep(0.1)
        continue

    # deviate
    if nav_state == "move" and seg_start_y is not None:
        if feet_y > seg_start_y + DEVIATE_Y:
            do_replan(state, f"deviate feet_y={feet_y} start={seg_start_y}")
            time.sleep(0.1)
            continue

    if nav_state == "idle":
        if path_idx >= len(path_plan):
            do_replan(state, "path exhausted")
            time.sleep(0.1)
            continue
        target_wx, target_wy, target_action = path_plan[path_idx]
        seg_start_y = feet_y
        if target_action == "bridge":
            nav_state = "bridge"
        elif target_action == "jump":
            nav_state = "jump"
        else:
            # move or fall — check if pillar needed
            streak_wy = _rise_streak_end(path_plan, path_idx)
            if feet_y - streak_wy > PILLAR_THRESH:
                target_wy = streak_wy
                nav_state = "pillar_stop"
            else:
                nav_state = "move"
        print(f"[nav] {nav_state} → ({target_wx},{target_wy}) action={target_action}")

    elif nav_state == "move":
        dx = (target_wx - pcx) * sign
        if dx <= ARRIVE_X:
            path_idx += 1
            nav_state = "idle"
        else:
            controller._post_control({direction: True})

    elif nav_state == "pillar_stop":
        vx = abs(p.velocity[0])
        if vx < 0.5:
            nav_state = "pillar"
        else:
            controller.release_all()

    elif nav_state == "pillar":
        jump_peak = _jump_peak_tiles(state.movement)
        rise = feet_y - target_wy
        print(f"[pillar] rise={rise:.1f} peak={jump_peak:.1f}")
        if rise <= jump_peak:
            nav_state = "move"
        else:
            controller.replay_skill(pillar_frames)
            time.sleep(len(pillar_frames) / 60.0)

    elif nav_state == "bridge":
        dx = (target_wx - pcx) * sign
        print(f"[bridge] dx={dx}")
        if dx <= ARRIVE_X:
            path_idx += 1
            nav_state = "idle"
        else:
            controller.replay_skill(bridge_frames)
            time.sleep(len(bridge_frames) / 60.0)

    elif nav_state == "jump":
        controller.replay_skill(jump_frames)
        time.sleep(len(jump_frames) / 60.0)
        path_idx += 1
        nav_state = "idle"

    time.sleep(0.05)
