import sys, os, time, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv()

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient, _is_standable_at
from terraria_agent.hand.mod_controller import ModController

perception = TerraBlindClient()
controller = ModController()

_SKILL_DIR = os.path.join(os.path.dirname(__file__), '..', 'skills')

def load_frames(name):
    path = os.path.join(_SKILL_DIR, f'{name}.json')
    data = json.loads(open(path).read())
    frames = data.get('frames', data) if isinstance(data, dict) else data
    result = []
    for f in frames:
        n = f.get('repeat', 1)
        base = {k: v for k, v in f.items() if k != 'repeat'}
        result.extend([base] * n)
    return result

def has_pit_ahead(state, sign, start=3, cols=10):
    tw = state.tile_window
    p = state.player
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    feet_y = int((p.pos[1] + p.height) / 16.0)
    for i in range(start, cols):
        cx = pcx + sign * i
        if not any(_is_standable_at(tw, cx, feet_y + dy) for dy in range(3)):
            return True
    return False

bridge_right = load_frames('bridge_right_2')
bridge_left  = load_frames('bridge_left_2')

print("默认向左走，遇到坑就铺桥，ctrl+c 退出")

while True:
    state = perception.detect(frame=None)
    if state is None or state.player.hp == 0:
        time.sleep(0.2)
        continue

    if has_pit_ahead(state, sign=-1):
        print("检测到左侧坑，铺桥...")
        while True:
            controller.replay_skill(bridge_left)
            time.sleep(len(bridge_left) / 60.0)
            state = perception.detect(frame=None)
            if state is None:
                break
            if not has_pit_ahead(state, sign=-1):
                print("坑填满，继续走")
                break
            print("坑未填满，继续铺...")
    else:
        controller._post_control({"left": True})

