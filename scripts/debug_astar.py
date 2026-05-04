import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient
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

        wx, wy, edge = path[0]
        target_wx, target_wy = wx, wy
        current_action = edge.action
        print(f"[astar] next=({wx},{wy}) action={edge.action} dx={edge.dx} dy={edge.dy} cost={edge.cost:.1f}")

        if current_action == "walk":
            nav_state = "walk"
        elif current_action == "jump":
            nav_state = "jump"
        elif current_action in ("pillar", "pillar_bridge"):
            nav_state = "stop"
        elif current_action == "bridge":
            nav_state = "bridge"

    elif nav_state == "walk":
        dx = abs(target_wx - pcx)
        if dx <= 1:
            print(f"[astar] walk arrived ({pcx},{feet_y})")
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
        print(f"[astar] pillar rise={rise:.1f} peak={jump_peak:.1f}")
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
        print(f"[astar] bridge dx={dx}")
        if dx <= 3:
            nav_state = "jump"
            print("[astar] bridge done → jump")
        else:
            frames = _load_skill_frames(f"bridge_{direction}_2")
            controller.replay_skill(frames)
            time.sleep(len(frames) / 60.0)

    elif nav_state == "jump":
        print(f"[astar] jump to ({target_wx},{target_wy})")
        jump_frames = [{"jump": True, direction: True}] * 15 + [{direction: True}] * 30
        controller.replay_skill(jump_frames)
        time.sleep(45 / 60.0)
        nav_state = "idle"

    time.sleep(0.2)
