import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient, _jump_peak_tiles
from terraria_agent.hand.mod_controller import ModController
from terraria_agent.terrain_nav import next_action
from terraria_agent.agent import _load_skill_frames

perception = TerraBlindClient()
controller = ModController()

_TILE = 16.0
_ARRIVE_THRESHOLD = 3

state_name = "walk"
target_x = None
target_y = None

bridge_frames = _load_skill_frames("bridge_right_2")
pillar_frames = _load_skill_frames("pillar_jump_2_height")

while True:
    state = perception.detect(frame=None)
    if state.player.hp == 0:
        time.sleep(0.2)
        continue

    p = state.player
    pcx = int((p.pos[0] + p.width / 2.0) / _TILE)
    feet_y = int((p.pos[1] + p.height) / _TILE)

    if state_name == "walk":
        action = next_action(state)
        if action and action.action != "walk":
            target_x = pcx + action.dist
            target_y = feet_y - action.delta
            print(f"目标: ({target_x},{target_y}) 右{action.dist}格 上{action.delta}格 → {action.action}")
            if action.action == "bridge":
                state_name = "pillar"
            else:
                state_name = "jump"
        else:
            print(f"\rwalk    ", end="", flush=True)
            controller._post_control({"right": True})

    elif state_name == "pillar":
        jump_peak = _jump_peak_tiles(state.movement)
        rise = feet_y - target_y
        dx = abs(pcx - target_x)
        dy = abs(feet_y - target_y)
        print(f"pillar: pos=({pcx},{feet_y}) target=({target_x},{target_y}) rise={rise:.1f} peak={jump_peak:.1f} dx={dx} dy={dy}")
        if dx <= _ARRIVE_THRESHOLD and dy <= _ARRIVE_THRESHOLD:
            print("→ 切换到 jump")
            state_name = "jump"
        elif rise <= jump_peak:
            print("→ 高度足够，开始搭桥")
            state_name = "bridge"
        else:
            controller.replay_skill(pillar_frames)
            time.sleep(len(pillar_frames) / 60.0)

    elif state_name == "bridge":
        dx = target_x - pcx
        dy = abs(feet_y - target_y)
        print(f"bridge: pos=({pcx},{feet_y}) target=({target_x},{target_y}) dx={dx} dy={dy}")
        if dx <= _ARRIVE_THRESHOLD:
            print("→ 切换到 jump")
            state_name = "jump"
        else:
            controller.replay_skill(bridge_frames)
            time.sleep(len(bridge_frames) / 60.0)

    elif state_name == "jump":
        print(f"jump: pos=({pcx},{feet_y}) target=({target_x},{target_y})")
        jump_frames = [{"jump": True, "right": True}] * 15 + [{"right": True}] * 30
        controller.replay_skill(jump_frames)
        time.sleep(45 / 60.0)
        state_name = "walk"
        target_x = None
        target_y = None

    time.sleep(0.2)
