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

_EXEC_TICK = 0.2
_TILE = 16.0
_STUCK_SECONDS = 2.0
_STUCK_SPEED_THRESHOLD = 0.5
_HP_DROP_THRESHOLD = 0.4
_TACTICIAN_INTERVAL = 60.0

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


class TriggerDetector:
    def __init__(self) -> None:
        self._prev_enemy_ids: set[int] = set()
        self._prev_terrain: TerrainType = TerrainType.FLAT
        self._prev_biome: str = ""
        self._prev_hp: int = -1
        self._prev_max_hp: int = 1
        self._prev_chest_ids: set[tuple[int, int]] = set()
        self._prev_drop_names: set[str] = set()
        self._moving_since: float | None = None

    def check(self, state: GameState, current_ctrl: dict, now: float) -> str | None:
        p = state.player

        has_horizontal = current_ctrl.get("left") or current_ctrl.get("right")
        on_ground = abs(p.velocity[1]) < 0.1
        if has_horizontal and on_ground and abs(p.velocity[0]) < _STUCK_SPEED_THRESHOLD:
            if self._moving_since is None:
                self._moving_since = now
            elif now - self._moving_since >= _STUCK_SECONDS:
                self._moving_since = None
                return "卡住"
        else:
            self._moving_since = None

        # 3. 血量骤降 40%
        if self._prev_hp >= 0:
            drop = self._prev_hp - p.hp
            if drop > self._prev_max_hp * _HP_DROP_THRESHOLD:
                self._prev_hp = p.hp
                return "血量骤降"
        self._prev_hp = p.hp
        self._prev_max_hp = p.max_hp

        # 4. 新敌人进入视野
        cur_ids = {e.who for e in state.enemies}
        new_enemies = cur_ids - self._prev_enemy_ids
        self._prev_enemy_ids = cur_ids
        if new_enemies:
            return "新敌人"

        # 5. 地形突变 flat → pit
        if self._prev_terrain == TerrainType.FLAT and state.terrain_ahead == TerrainType.PIT:
            self._prev_terrain = state.terrain_ahead
            return "地形突变_pit"
        self._prev_terrain = state.terrain_ahead

        # 6. 生物群系切换
        if self._prev_biome and self._prev_biome != state.biome:
            self._prev_biome = state.biome
            return "生物群系切换"
        self._prev_biome = state.biome

        # 8. 新武器或水果掉落
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

        # 9. 发现新箱子
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

def _load_skill_frames(name: str) -> list:
    import json
    path = _SKILL_DIR / f"{name}.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        frames = data.get("frames", [])
    else:
        frames = data
    result = []
    for f in frames:
        n = f.get("repeat", 1)
        base = {k: v for k, v in f.items() if k != "repeat"}
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

def _safety_interrupt(state) -> str | None:
    if state.player.hp < state.player.max_hp * 0.3:
        return "血量低"
    return None


def run() -> None:
    perception = TerraBlindClient()
    controller = ModController()
    llm = LLMClient()
    tactician = Tactician()
    trigger = TriggerDetector()
    print("[agent] 启动 — ctrl+c 停止")

    current_ctrl: dict = {"right": True}
    pending: dict | None = None
    pending_lock = threading.Lock()
    visited_biomes: list[str] = []
    tactician_last: float = 0.0
    _prev_overhead: bool = False

    def llm_worker(state_text: str, trigger_reason: str) -> None:
        nonlocal pending
        goal = tactician.goal
        goal_line = f"[目标:{goal}]\n" if goal else ""
        full_text = f"{goal_line}[触发:{trigger_reason}]\n{state_text}"
        decision = llm.decide(full_text)
        with pending_lock:
            pending = decision if decision else {}

    llm_thread: threading.Thread | None = None
    deadline: float = 0.0

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
            macro_text = serialize_macro(state, goal=tactician.goal, visited_biomes=visited_biomes)
            tactician.start(macro_text)

        reason = _safety_interrupt(state)
        if reason:
            print(f"[agent] 安全中断: {reason}")
            current_ctrl = {"left": True}
            deadline = now + 3.0

        with pending_lock:
            if pending is not None:
                decision = pending
                pending = None
                thought = decision.get("思考", "")
                duration = float(decision.get("持续秒数", 1.0))
                skill_name = decision.get("skill")
                if skill_name:
                    resolved = skill_execute(skill_name, state, controller)
                    if resolved:
                        ctrl = resolved.get("ctrl", {})
                        duration = resolved.get("duration", duration)
                        print(f"[决策] {thought} → {skill_name} ({duration}s)")
                    else:
                        print(f"[决策] {thought} → {skill_name} 未找到")
                        ctrl = {}
                else:
                    ctrl = decision.get("控制", {})
                    print(f"[决策] {thought} → inline ({duration}s)")
                if ctrl:
                    current_ctrl = ctrl
                    deadline = now + duration

        llm_idle = llm_thread is None or not llm_thread.is_alive()
        if llm_idle:
            trigger_reason = None
            if now >= deadline:
                trigger_reason = "deadline"
            else:
                trigger_reason = trigger.check(state, current_ctrl, now)

            if trigger_reason:
                state_text = serialize(state)
                print(f"[触发:{trigger_reason}]")
                llm_thread = threading.Thread(
                    target=llm_worker, args=(state_text, trigger_reason), daemon=True
                )
                llm_thread.start()

        cave = cave_detect(state)
        if cave:
            _, cave_dir, walk_back, rise_tiles = cave
            print(f"[cave bypass] dir={cave_dir}")
            current_ctrl = {}
            deadline = now + 999
            threading.Thread(
                target=_cave_bypass_worker,
                args=(controller, cave_dir),
                daemon=True,
            ).start()

        reflex_ctrl = reflex_check(state)
        if reflex_ctrl:
            actions = _parse_actions(reflex_ctrl, state)
        elif current_ctrl:
            actions = _parse_actions(current_ctrl, state)
        else:
            actions = [GameAction(action=ActionType.NONE)]
        controller.execute(actions)

        time.sleep(_EXEC_TICK)


if __name__ == "__main__":
    run()
