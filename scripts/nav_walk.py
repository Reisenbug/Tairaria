import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient, _jump_peak_tiles
from terraria_agent.hand.mod_controller import ModController
from terraria_agent.terrain_nav import next_action
from terraria_agent.agent import _load_skill_frames, TriggerDetector

_TILE = 16.0
_TRIGGER_DIST = 8
_ARRIVE_THRESHOLD = 3

perception = TerraBlindClient()
controller = ModController()
trigger = TriggerDetector()

bridge_frames = _load_skill_frames("bridge_right_2")
pillar_frames = _load_skill_frames("pillar_jump_2_height")

state_name = "walk"
target_x = None
target_y = None
current_ctrl = {"right": True}

while True:
    now = time.time()
    state = perception.detect(frame=None)
    if state.player.hp == 0:
        time.sleep(0.2)
        continue

    p = state.player
    pcx = int((p.pos[0] + p.width / 2.0) / _TILE)
    feet_y = int((p.pos[1] + p.height) / _TILE)

    stuck = trigger.check(state, current_ctrl, now)
    if stuck:
        print(f"[卡住] pos=({pcx},{feet_y}) state={state_name}")

    if state_name == "walk":
        action = next_action(state)
        if action and action.action != "walk" and action.dist <= _TRIGGER_DIST:
            target_x = pcx + action.dist
            target_y = feet_y - action.delta
            print(f"[E检测] 右{action.dist}格 上{action.delta}格 → {action.action} target=({target_x},{target_y})")
            state_name = "pillar"
            current_ctrl = {}
        else:
            controller._post_control({"right": True})
            current_ctrl = {"right": True}

    elif state_name == "pillar":
        jump_peak = _jump_peak_tiles(state.movement)
        rise = feet_y - target_y
        print(f"[pillar] pos=({pcx},{feet_y}) rise={rise:.1f} peak={jump_peak:.1f}")
        if rise <= jump_peak:
            print("[pillar] 高度足够 → bridge")
            state_name = "bridge"
        else:
            controller.replay_skill(pillar_frames)
            time.sleep(len(pillar_frames) / 60.0)

    elif state_name == "bridge":
        dx = target_x - pcx
        print(f"[bridge] pos=({pcx},{feet_y}) dx={dx}")
        if dx <= _ARRIVE_THRESHOLD:
            print("[bridge] 到达边缘 → jump")
            state_name = "jump"
        else:
            controller.replay_skill(bridge_frames)
            time.sleep(len(bridge_frames) / 60.0)

    elif state_name == "jump":
        print(f"[jump] pos=({pcx},{feet_y}) target=({target_x},{target_y})")
        jump_frames = [{"jump": True, "right": True}] * 15 + [{"right": True}] * 30
        controller.replay_skill(jump_frames)
        time.sleep(45 / 60.0)
        state_name = "walk"
        target_x = None
        target_y = None
        current_ctrl = {"right": True}

    time.sleep(0.2)
