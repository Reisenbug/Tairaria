from __future__ import annotations

import time
import threading

from dotenv import load_dotenv
load_dotenv()

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient
from terraria_agent.geometry import player_center_world, world_to_screen
from terraria_agent.hand.mod_controller import ModController
from terraria_agent.llm_client import LLMClient
from terraria_agent.models.actions import ActionType, GameAction
from terraria_agent.models.game_state import GameState, TerrainType
from terraria_agent.cave_detector import detect as cave_detect
from terraria_agent.reflex import check as reflex_check
from terraria_agent.skill_registry import execute as skill_execute
from terraria_agent.state_serializer import serialize, serialize_macro
from terraria_agent.tactician import Tactician
from terraria_agent.goal_executor import GoalExecutor
from terraria_agent.hand.hotbar_organizer import organize_hotbar

_EXEC_TICK = 0.2
_TILE = 16.0
_STUCK_SECONDS = 1.0
_STUCK_SPEED_THRESHOLD = 0.5
_HP_DROP_THRESHOLD = 0.4
_TACTICIAN_INTERVAL = 60.0
_DEFAULT_DEADLINE = 10.0

_FRUITS = {
    "苹果", "杏", "葡萄柚", "柠檬", "桃子",
    "樱桃", "李子",
    "黑醋栗", "接骨木果",
    "血橙", "红毛丹",
    "芒果", "菠萝",
    "香蕉", "椰子",
    "火龙果", "杨桃",
    "石榴", "辣椒",
}
_WEAPONS_CATEGORY = "weapon"


_STUCK_WINDOW = 3.0
_STUCK_NET_TILES = 1.0

class TriggerDetector:
    def __init__(self) -> None:
        self._prev_enemy_ids: set[int] = set()
        self._prev_terrain: TerrainType = TerrainType.FLAT
        self._prev_biome: str = ""
        self._prev_hp: int = -1
        self._prev_max_hp: int = 1
        self._prev_chest_ids: set[tuple[int, int]] = set()
        self._prev_drop_names: set[str] = set()
        self._pos_history: list[tuple[float, float]] = []

    def check(self, state: GameState, current_ctrl: dict, now: float) -> str | None:
        p = state.player

        has_horizontal = current_ctrl.get("left") or current_ctrl.get("right")
        if has_horizontal:
            self._pos_history.append((now, p.pos[0]))
            self._pos_history = [(t, x) for t, x in self._pos_history if now - t <= _STUCK_WINDOW]
            if len(self._pos_history) >= 2:
                oldest_x = self._pos_history[0][1]
                net = abs(p.pos[0] - oldest_x) / _TILE
                elapsed = now - self._pos_history[0][0]
                if elapsed >= _STUCK_WINDOW and net < _STUCK_NET_TILES:
                    self._pos_history.clear()
                    return "卡住"
        else:
            self._pos_history.clear()
        if self._prev_hp >= 0:
            drop = self._prev_hp - p.hp
            if drop > self._prev_max_hp * _HP_DROP_THRESHOLD:
                self._prev_hp = p.hp
                return "血量骤降"
        self._prev_hp = p.hp
        self._prev_max_hp = p.max_hp

        cur_ids = {e.who for e in state.enemies}
        self._prev_enemy_ids = cur_ids
        if self._prev_terrain == TerrainType.FLAT and state.terrain_ahead == TerrainType.PIT:
            self._prev_terrain = state.terrain_ahead
            return "地形突变_pit"
        self._prev_terrain = state.terrain_ahead
        if self._prev_biome and self._prev_biome != state.biome:
            self._prev_biome = state.biome
            return "生物群系切换"
        self._prev_biome = state.biome
        cur_drop_names = {d.name for d in state.dropped_items}
        new_drops = cur_drop_names - self._prev_drop_names
        self._prev_drop_names = cur_drop_names
        for name in new_drops:
            if name in _FRUITS:
                return f"掉落_水果_{name}"
        for d in state.dropped_items:
            if d.name in new_drops:
                slot = next((s for s in state.inventory_slots if s.name == d.name), None)
                if slot and slot.category == _WEAPONS_CATEGORY:
                    return f"掉落_武器_{d.name}"
        cur_chests = {o.tile_pos for o in state.objects if o.type == "chest"}
        new_chests = cur_chests - self._prev_chest_ids
        self._prev_chest_ids = cur_chests
        if new_chests:
            return "发现箱子"

        return None


def _parse_actions(ctrl: dict, state: GameState) -> list[GameAction]:
    actions: list[GameAction] = []

    if ctrl.get("quick_heal"):
        actions.append(GameAction(action=ActionType.QUICK_HEAL))
        return actions

    if ctrl.get("loot_all"):
        actions.append(GameAction(action=ActionType.LOOT_ALL))

    if ctrl.get("interact"):
        tile_x = ctrl.get("tile_x")
        tile_y = ctrl.get("tile_y")
        if tile_x is not None and tile_y is not None:
            actions.append(GameAction(action=ActionType.INTERACT, tile=(int(tile_x), int(tile_y))))

    if "selected_slot" in ctrl:
        actions.append(GameAction(action=ActionType.SWITCH_SLOT, slot=int(ctrl["selected_slot"])))

    for direction in ("left", "right", "up", "down"):
        if ctrl.get(direction):
            actions.append(GameAction(action=ActionType.MOVE, direction=direction))

    if ctrl.get("jump"):
        actions.append(GameAction(action=ActionType.JUMP))

    if ctrl.get("use_item"):
        mx = ctrl.get("mx")
        my = ctrl.get("my")
        if mx is not None and my is not None:
            actions.append(GameAction(action=ActionType.USE_ITEM_MOD, mx=float(mx), my=float(my)))
        else:
            screen_xy = ctrl.get("screen_xy")
            if screen_xy is None:
                rel_x = ctrl.get("mouse_x")
                rel_y = ctrl.get("mouse_y")
                if rel_x is not None and rel_y is not None:
                    pcx, pcy = player_center_world(state.player)
                    world_xy = (pcx + float(rel_x) * _TILE, pcy + float(rel_y) * _TILE)
                    screen_xy = world_to_screen(world_xy, state.camera)
            actions.append(GameAction(action=ActionType.ATTACK, target=screen_xy))

    if not actions:
        actions.append(GameAction(action=ActionType.NONE))

    return actions


_SKILL_DIR = __import__("pathlib").Path(__file__).parent.parent.parent / "skills"

def _mirror_frame(f: dict) -> dict:
    m = dict(f)
    if "mx" in m:
        m["mx"] = -m["mx"]
    if m.get("right"):
        del m["right"]
        m["left"] = True
    elif m.get("left"):
        del m["left"]
        m["right"] = True
    return m


def _load_skill_frames(name: str) -> list:
    import json
    path = _SKILL_DIR / f"{name}.json"
    mirror = False
    if not path.exists() and name.endswith("_left"):
        path = _SKILL_DIR / f"{name[:-5]}_right.json"
        mirror = True
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    frames = data.get("frames", []) if isinstance(data, dict) else data
    result = []
    for f in frames:
        n = f.get("repeat", 1)
        base = {k: v for k, v in f.items() if k != "repeat"}
        if mirror:
            base = _mirror_frame(base)
        result.extend([base] * n)
    return result

def _poll_walk_done(timeout: float = 10.0) -> bool:
    import json, urllib.request
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.1)
        try:
            with urllib.request.urlopen("http://127.0.0.1:17878/state", timeout=0.5) as r:
                data = json.loads(r.read())
            if data.get("walk_to_edge_done"):
                return True
        except Exception:
            pass
    return False

def _cave_bypass_worker(controller, cave_dir: str) -> None:
    opposite = "left" if cave_dir == "right" else "right"
    print(f"[cave bypass] walk_to_edge dir={opposite}")
    controller.walk_to_edge(opposite, extra_tiles=1.0)
    if not _poll_walk_done():
        print("[cave bypass] walk_to_edge 超时")
        return
    skill_name = f"cave_bypass_{cave_dir}"
    frames = _load_skill_frames(skill_name)
    if not frames:
        print(f"[cave bypass] 找不到 skill 文件: {skill_name}.json")
        return
    print(f"[cave bypass] replay {len(frames)} 帧")
    controller.replay_skill(frames)

def _overhead_clear(state) -> bool:
    tw = state.tile_window
    if tw is None:
        return True
    p = state.player
    head_y = int(p.pos[1] / 16.0)
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    for col in (pcx, pcx + 1):
        for dy in range(1, 11):
            t = tw.tile_at(col, head_y - dy)
            if t is not None and t.solid:
                return False
    return True


def _overhead_shallow(state) -> bool:
    tw = state.tile_window
    if tw is None:
        return False
    p = state.player
    head_y = int(p.pos[1] / 16.0)
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    for col in (pcx, pcx + 1):
        for dy in range(1, 4):
            t = tw.tile_at(col, head_y - dy)
            if t is not None and t.solid:
                return True
    return False


def _handle_stuck(state, controller=None, pickaxe_slot=None, perception=None) -> bool:
    from terraria_agent.pit_detector import _surface_y
    p = state.player
    tw = state.tile_window
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    feet_y = int((p.pos[1] + p.height) / 16.0)
    sign = 1 if p.direction == "right" else -1
    surf = []
    for i in range(1, 16):
        cx = pcx + sign * i
        sy = _surface_y(tw, cx, feet_y - 1) if tw else None
        surf.append(sy - feet_y if sy is not None else "?")
    overhead_clear = _overhead_clear(state)
    shallow = _overhead_shallow(state)
    print(f"[卡住诊断] pos=({pcx},{feet_y}) dir={p.direction} overhead_clear={overhead_clear} shallow={shallow}")
    print(f"[卡住诊断] 前方地表相对高度: {surf}")
    if state.terrain_scan:
        ts = state.terrain_scan
        print(f"[卡住诊断] terrain={ts.terrain_type.value} dist={ts.distance_tiles} size={ts.depth_or_height}")
    if tw:
        rows = []
        for dy in range(-15, 1):
            row = ""
            for dx in range(-20, 21):
                cx, cy = pcx + dx, feet_y + dy
                if abs(dx) <= 1 and dy >= -3 and dy <= 0:
                    row += "@"
                    continue
                t = tw.tile_at(cx, cy)
                if t is None:
                    row += "?"
                elif t.lava:
                    row += "L"
                elif t.water:
                    row += "~"
                elif t.platform:
                    row += "="
                elif t.solid:
                    row += "#"
                else:
                    row += "."
            rows.append(row)
        print("[卡住地图] (顶=头顶15格, 底=脚底, @=玩家, #=solid, ==platform, ~=水, L=岩浆)")
        for row in rows:
            print(" " + row)
    if shallow and controller is not None and pickaxe_slot is not None and perception is not None:
        print(f"[卡住] 头顶有方块，向上挖掘...")
        dig_frames = (
            [{"use_item": True, "sc": 1, "selected_slot": pickaxe_slot, "mx": 0, "my": -5, "jump": True}] * 15 +
            [{"use_item": True, "sc": 1, "selected_slot": pickaxe_slot, "mx": 0, "my": -5}] * 15
        )
        import threading as _threading
        def _dig_up_worker():
            for _ in range(10):
                controller.replay_skill(dig_frames)
                import time as _time
                _time.sleep(len(dig_frames) / 60.0)
                s = perception.detect(frame=None)
                if s and _overhead_clear(s):
                    break
            dir_name = state.player.direction
            frames = _load_skill_frames(f"big_pillar_jump_{dir_name}")
            if frames:
                print(f"[卡住] 挖穿，触发 big_pillar_jump_{dir_name}")
                controller.replay_skill(frames)
        _threading.Thread(target=_dig_up_worker, daemon=True).start()
        return True
    return False


def _safety_interrupt(state, controller, fight_active) -> str | None:
    p = state.player
    if p.hp >= p.max_hp * 0.3:
        return None
    controller._http_fire("http://127.0.0.1:17878/quick_heal")
    if fight_active[0]:
        controller.fight_stop()
        fight_active[0] = False
    return "血量低"


def run() -> None:
    perception = TerraBlindClient()
    controller = ModController()
    llm = LLMClient()
    tactician = Tactician()
    trigger = TriggerDetector()
    goal_exec = GoalExecutor(controller)
    print("[agent] 启动 — ctrl+c 停止")

    first_state = None
    while first_state is None or first_state.player.hp == 0:
        first_state = perception.detect(frame=None)
        time.sleep(0.5)
    organize_hotbar(first_state.inventory_slots)
    print("[agent] hotbar 整理完成")

    current_ctrl: dict = {"right": True}
    pending: dict | None = None
    pending_lock = threading.Lock()
    visited_biomes: list[str] = []
    tactician_last: float = 0.0
    _prev_overhead: bool = False
    _fight_deadline: float = 0.0
    _trees_chopped = [0]
    _TREE_HEIGHT_MIN = 15
    _TREE_CHOP_LIMIT = 2

    def llm_worker(state_text: str, trigger_reason: str) -> None:
        nonlocal pending
        goal = tactician.goal
        goal_line = f"[目标:{goal}]\n" if goal else ""
        ctx_lines = "\n".join(_pending_context)
        _pending_context.clear()
        ctx_part = f"[事件]\n{ctx_lines}\n" if ctx_lines else ""
        full_text = f"{goal_line}{ctx_part}[触发:{trigger_reason}]\n{state_text}"
        decision = llm.decide(full_text)
        with pending_lock:
            pending = decision if decision else {}

    llm_thread: threading.Thread | None = None
    deadline: float = time.time() + _DEFAULT_DEADLINE
    _pending_context: list[str] = []
    FightCoordinator_active = [False]
    _prev_tool_weapon_slots: set[int] = set()
    _cave_bypass_active = [False]
    _explore_direction: str = "right"

    while True:
        now = time.time()
        state = perception.detect(frame=None)
        if state.player.hp == 0:
            print("[agent] 等待游戏状态...")
            time.sleep(2.0)
            continue

        if state.biome and (not visited_biomes or visited_biomes[-1] != state.biome):
            visited_biomes.append(state.biome)

        if tactician.is_idle() and now - tactician_last >= _TACTICIAN_INTERVAL:
            tactician_last = now
            macro_text = serialize_macro(state, goal=tactician.goal, visited_biomes=visited_biomes,
                                         explore_direction=_explore_direction)
            tactician.start(macro_text)
            goal = tactician.goal
            if "右" in goal or "right" in goal.lower():
                _explore_direction = "right"
            elif "左" in goal or "left" in goal.lower():
                _explore_direction = "left"

        cur_tool_weapon = {s.slot_index for s in state.inventory_slots
                           if not s.is_empty and (s.is_weapon or s.is_axe or s.is_pickaxe)}
        if cur_tool_weapon - _prev_tool_weapon_slots:
            organize_hotbar(state.inventory_slots)
        _prev_tool_weapon_slots = cur_tool_weapon

        reason = _safety_interrupt(state, controller, FightCoordinator_active)
        if reason:
            print(f"[agent] 安全中断: {reason}")
            if state.enemies:
                nearest = min(state.enemies, key=lambda e: e.distance)
                p = state.player
                retreat_dir = "left" if nearest.pos[0] > p.pos[0] else "right"
            else:
                retreat_dir = "left" if state.player.direction == "right" else "right"
            current_ctrl = {retreat_dir: True}
            deadline = now + 5.0

        with pending_lock:
            if pending is not None:
                decision = pending
                pending = None
                thought = decision.get("思考", "")
                duration = float(decision.get("持续秒数", _DEFAULT_DEADLINE))
                goal_name = decision.get("goal")
                skill_name = decision.get("skill") if not goal_name else None
                if goal_name and not goal_exec.active:
                    target = decision.get("target", {})
                    timeout = float(decision.get("timeout", 15.0))
                    def _on_goal_done(result: str) -> None:
                        print(f"[goal] 完成: {result}")
                        nonlocal deadline
                        organize_hotbar(state.inventory_slots)
                        if "stuck" in result:
                            ps = next((s.slot_index for s in state.inventory_slots[:10] if s.is_pickaxe), None)
                            _handle_stuck(state, controller, ps, perception)
                        deadline = 0.0
                    goal_exec.start(goal_name, target, timeout, _on_goal_done)
                    current_ctrl = {}
                    deadline = now + timeout + 2.0
                    print(f"[决策] {thought} → goal:{goal_name} target={target}")
                elif goal_name:
                    print(f"[决策] {thought} → goal:{goal_name} 已有 goal 进行中，跳过")
                _FIGHT_SKILLS = {"fight_nearest", "fight_moving_right", "fight_moving_left"}
                if skill_name == "craft":
                    item_id = decision.get("item_id", -1)
                    amount = int(decision.get("amount", 1))
                    result = controller.craft(item_id=item_id, amount=amount)
                    print(f"[决策] {thought} → craft item_id={item_id} amount={amount} result={result}")
                    ctrl = {}
                    duration = 1.0
                elif skill_name in _FIGHT_SKILLS:
                    controller.fight_start()
                    _fight_deadline = now + duration
                    ctrl = {}
                    if skill_name == "fight_moving_right":
                        ctrl["right"] = True
                    elif skill_name == "fight_moving_left":
                        ctrl["left"] = True
                    current_ctrl = ctrl
                    deadline = now + duration
                    print(f"[决策] {thought} → {skill_name} ({duration}s)")
                elif skill_name:
                    resolved = skill_execute(skill_name, state, controller)
                    if resolved:
                        ctrl = resolved.get("ctrl", {})
                        duration = resolved.get("duration", duration)
                        print(f"[决策] {thought} → {skill_name} ({duration}s)")
                    else:
                        print(f"[决策] {thought} → {skill_name} 未找到")
                        ctrl = {}
                elif not goal_name:
                    ctrl = decision.get("控制", {})
                    print(f"[决策] {thought} → inline ({duration}s)")
                if ctrl:
                    current_ctrl = ctrl
                deadline = now + max(duration, _DEFAULT_DEADLINE)

        llm_idle = llm_thread is None or not llm_thread.is_alive()
        if llm_idle:
            trigger_reason = None
            if now >= deadline:
                trigger_reason = "deadline"
            else:
                trigger_reason = trigger.check(state, current_ctrl, now)

            if trigger_reason:
                state_text = serialize(state, focus=trigger_reason)
                state_text += f"\ntrees_chopped={_trees_chopped[0]}/{_TREE_CHOP_LIMIT}"
                print(f"[触发:{trigger_reason}]")
                if trigger_reason == "卡住":
                    pickaxe_slot = next((s.slot_index for s in state.inventory_slots[:10] if s.is_pickaxe), None)
                    if _handle_stuck(state, controller, pickaxe_slot, perception):
                        continue
                llm_thread = threading.Thread(
                    target=llm_worker, args=(state_text, trigger_reason), daemon=True
                )
                llm_thread.start()

        if state.enemies:
            if not FightCoordinator_active[0]:
                controller.fight_start()
                FightCoordinator_active[0] = True
        else:
            if FightCoordinator_active[0]:
                controller.fight_stop()
                FightCoordinator_active[0] = False

        if _fight_deadline > 0 and now >= _fight_deadline:
            controller.fight_stop()
            _fight_deadline = 0.0

        if not goal_exec.active and _trees_chopped[0] < _TREE_CHOP_LIMIT:
            big_trees = [o for o in state.objects if o.type == "tree" and o.height >= _TREE_HEIGHT_MIN]
            if big_trees:
                _trees_chopped[0] += 1
                inv_before = dict(state.inventory)
                saved_ctrl = dict(current_ctrl)
                def _on_tree_done(result: str) -> None:
                    nonlocal deadline, current_ctrl
                    if "done" in result:
                        inv_after = state.inventory
                        gained = {k: inv_after.get(k, 0) - inv_before.get(k, 0)
                                  for k in inv_after if inv_after.get(k, 0) > inv_before.get(k, 0)}
                        print(f"[tree] 砍完第{_trees_chopped[0]}棵 gained={gained}")
                        if gained:
                            _pending_context.append(f"砍树完成，获得:{gained}")
                        organize_hotbar(state.inventory_slots)
                        if _trees_chopped[0] >= _TREE_CHOP_LIMIT:
                            result = controller.craft(item_id=94, amount=50)
                            print(f"[tree] 自动制作木平台: {result}")
                            organize_hotbar(state.inventory_slots)
                        current_ctrl = saved_ctrl
                        deadline = 0.0
                goal_exec.start("chop_tree", {"type": "tree"}, timeout=30, on_done=_on_tree_done)
                current_ctrl = {}

        cave = cave_detect(state)
        if cave and not _cave_bypass_active[0] and not goal_exec.active:
            _, cave_dir, walk_back, rise_tiles = cave
            print(f"[cave bypass] dir={cave_dir}")
            current_ctrl = {}
            deadline = now + 999
            _cave_bypass_active[0] = True
            def _cave_done_cb(cave_dir=cave_dir):
                nonlocal deadline, current_ctrl
                current_ctrl = {"right": True}
                deadline = 0.0
                _cave_bypass_active[0] = False
            def _cave_thread(cave_dir=cave_dir):
                _cave_bypass_worker(controller, cave_dir)
                _cave_done_cb()
            threading.Thread(target=_cave_thread, daemon=True).start()

        reflex_ctrl = reflex_check(state)
        if reflex_ctrl:
            actions = _parse_actions(reflex_ctrl, state)
        elif goal_exec.active:
            goal_ctrl = goal_exec.tick(state)
            if goal_ctrl:
                controller._post_control(goal_ctrl)
                time.sleep(_EXEC_TICK)
                continue
            else:
                actions = [GameAction(action=ActionType.NONE)]
        elif current_ctrl:
            actions = _parse_actions(current_ctrl, state)
        else:
            actions = [GameAction(action=ActionType.NONE)]
        controller.execute(actions)

        time.sleep(_EXEC_TICK)


if __name__ == "__main__":
    run()
