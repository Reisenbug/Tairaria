import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv()

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient
from terraria_agent.hand.mod_controller import ModController
from terraria_agent.goal_executor import GoalExecutor

perception = TerraBlindClient()
controller = ModController()
goal_exec = GoalExecutor(controller)

_TREE_HEIGHT_MIN = 15
_TREE_CHOP_LIMIT = 2
_trees_chopped = [0]

print(f"砍{_TREE_CHOP_LIMIT}棵高树后停止，找不到就向右走，ctrl+c 退出")

while True:
    state = perception.detect(frame=None)
    if state is None or state.player.hp == 0:
        time.sleep(0.2)
        continue

    if _trees_chopped[0] >= _TREE_CHOP_LIMIT:
        controller.release_all()
        print(f"已砍完{_TREE_CHOP_LIMIT}棵树，停止")
        break

    if goal_exec.active:
        goal_ctrl = goal_exec.tick(state)
        if goal_ctrl:
            controller._post_control(goal_ctrl)
        time.sleep(0.1)
        continue

    big_trees = [o for o in state.objects if o.type == "tree" and o.height >= _TREE_HEIGHT_MIN]
    if big_trees:
        _trees_chopped[0] += 1
        print(f"发现高树，开始砍第{_trees_chopped[0]}棵")
        def _on_done(result: str) -> None:
            print(f"[tree] {result}")
        goal_exec.start("chop_tree", {"type": "tree"}, timeout=30, on_done=_on_done)
    else:
        print(f"没找到高树，向右走...", end="\r")
        controller._post_control({"right": True})

    time.sleep(0.2)
