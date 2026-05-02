import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv()

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient
from terraria_agent.hand.mod_controller import ModController
from terraria_agent.agent import _overhead_clear, _load_skill_frames

perception = TerraBlindClient()
controller = ModController()

print("等待游戏状态...")
while True:
    state = perception.detect(frame=None)
    if state and state.player.hp > 0:
        break
    time.sleep(0.2)

p = state.player
overhead_clear = _overhead_clear(state)
print(f"pos=({p.pos[0]:.0f},{p.pos[1]:.0f}) dir={p.direction} overhead_clear={overhead_clear}")

if overhead_clear:
    print("头顶空旷，无需挖掘")
else:
    pickaxe_slot = next((s.slot_index for s in state.inventory_slots[:10] if s.is_pickaxe), None)
    if pickaxe_slot is None:
        print("没有镐子，无法挖掘")
    else:
        dig_frames = (
            [{"use_item": True, "sc": 1, "selected_slot": pickaxe_slot, "mx": 0, "my": -5, "jump": True}] * 15 +
            [{"use_item": True, "sc": 1, "selected_slot": pickaxe_slot, "mx": 0, "my": -5}] * 15
        )
        print(f"头顶有方块，开始向上挖 (pickaxe slot={pickaxe_slot})...")
        for _ in range(10):
            controller.replay_skill(dig_frames)
            time.sleep(len(dig_frames) / 60.0)
            state = perception.detect(frame=None)
            c = _overhead_clear(state)
            print(f"  overhead_clear={c}")
            if c:
                print("挖穿！")
                break

        dir_name = state.player.direction
        frames = _load_skill_frames(f"big_pillar_jump_{dir_name}")
        if frames:
            print(f"触发 big_pillar_jump_{dir_name} ({len(frames)} frames)")
            controller.replay_skill(frames)
        else:
            print(f"找不到 big_pillar_jump_{dir_name}")
