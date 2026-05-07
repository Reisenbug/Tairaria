import sys, os, time, json, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from pynput import keyboard as _kb
from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient, scan_skyline
from terraria_agent.hand.mod_controller import ModController
from terraria_agent.terrain_astar import astar, astar_debug_path
from terraria_agent.agent import _load_skill_frames, _mirror_frame
from terraria_agent.cerebellum.terra_blind_client import _jump_peak_tiles

perception = TerraBlindClient()
controller = ModController()
_BASE = "http://127.0.0.1:17878"

_paused = False
_last_path = []

def _on_press(key):
    global _paused
    try:
        if key.char == 'l' and not _paused:
            _paused = True
            controller._post_control({})
            print("[PAUSED]")
            last_state = perception.detect(frame=None)
            last_tw = last_state.tile_window
            from terraria_agent.cerebellum.terra_blind_client import scan_standable as _scan_standable
            for wx, wy, edge in _last_path:
                src_wx = wx - edge.dx
                src_wy = wy + edge.dy
                reason = f" [{edge.reason}]" if edge.reason else ""
                print(f"  ({src_wx},{src_wy})→({wx},{wy}) {edge.action} dx={edge.dx} dy={edge.dy} cost={edge.cost:.1f}{reason}")
                if edge.action in ("bridge", "pillar_bridge"):
                    astar_debug_path(last_state, sign, (src_wx, src_wy), (wx, wy))
        elif key.char == 'p' and _paused:
            _paused = False
            print("[RESUMED]")
    except AttributeError:
        pass

_kb.Listener(on_press=_on_press, daemon=True).start()

def _post(path, data):
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(_BASE + path, data=body, method="POST")
        urllib.request.urlopen(req, timeout=1)
    except Exception:
        pass

direction = "left"
sign = 1 if direction == "right" else -1

_ACTION_COLOR = {
    "walk":         (100, 220, 255),
    "jump":         (100, 255, 100),
    "bridge":       (255, 180,   0),
    "pillar":       (255,  80,  80),
    "pillar_bridge":(255,  80, 255),
}

def _send_path_vis(path, pcx, feet_y):
    tiles = [{"wx": pcx, "wy": feet_y, "r": 255, "g": 255, "b": 255}]
    labels = []
    cx0, cy0 = pcx, feet_y
    for wx, wy, edge in path:
        r, g, b = _ACTION_COLOR.get(edge.action, (255, 255, 255))
        steps = abs(wx - cx0)
        for i in range(steps + 1):
            t = i / max(steps, 1)
            ix = int(cx0 + (wx - cx0) * t)
            iy = int(cy0 + (wy - cy0) * t)
            tiles.append({"wx": ix, "wy": iy, "r": r, "g": g, "b": b})
        reason_str = f" {edge.reason}" if edge.reason else ""
        labels.append({"wx": wx, "wy": wy,
                       "text": f"{edge.action} c={edge.cost:.0f} dx={edge.dx} dy={edge.dy}{reason_str}",
                       "r": r, "g": g, "b": b})
        cx0, cy0 = wx, wy
    _post("/path_vis_tiles", tiles)
    _post("/debug_labels", labels)

nav_state = "idle"
path_plan = []
path_idx = 0
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

while True:
    if _paused:
        time.sleep(0.1)
        continue
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
    head_y = int(p.pos[1] / 16.0)

    now = time.time()
    if now - last_sample_t >= _STALL_SAMPLE_SEC:
        if nav_state != "idle" and last_sample_pcx == pcx:
            stall_count += 1
            if stall_count >= _STALL_LIMIT:
                print(f"[stall] pos=({pcx},{feet_y})")
                controller._post_control({})
                nav_state = "idle"
                path_plan = []
                stall_count = 0
        else:
            stall_count = 0
        last_sample_pcx = pcx
        last_sample_t = now

    skyline = scan_skyline(tw)
    sky_y = skyline.get(pcx)
    in_pit = sky_y is not None and feet_y > sky_y + 4
    if in_pit:
        controller._post_control({"left" if direction == "right" else "right": True})
        nav_state = "idle"
        path_plan = []
        continue

    def _on_fail(standable, explored, start, goal):
        tiles = []
        for (wx, wy) in standable:
            if (wx, wy) in explored:
                tiles.append({"wx": wx, "wy": wy, "r": 180, "g": 180, "b": 180})
            else:
                tiles.append({"wx": wx, "wy": wy, "r": 255, "g": 60, "b": 60})
        tiles.append({"wx": start[0], "wy": start[1], "r": 255, "g": 255, "b": 255})
        tiles.append({"wx": goal[0], "wy": goal[1], "r": 255, "g": 160, "b": 0})
        _post("/path_vis_tiles", tiles)

    if nav_state == "idle":
        if path_plan and path_idx < len(path_plan):
            target_wx, target_wy, edge = path_plan[path_idx]
            current_action = edge.action
            nav_state = "walk" if current_action == "walk" else \
                        "jump" if current_action == "jump" else \
                        "stop" if current_action in ("pillar", "pillar_bridge") else \
                        "bridge"
            walk_start_y = feet_y if nav_state == "walk" else None
        else:
            path_plan = astar(state, sign, on_fail=_on_fail)
            if not path_plan:
                time.sleep(0.5)
                continue
            path_idx = 0
            _last_path = path_plan
            _send_path_vis(path_plan, pcx, feet_y)
            target_wx, target_wy, edge = path_plan[0]
            current_action = edge.action
            nav_state = "walk" if current_action == "walk" else \
                        "jump" if current_action == "jump" else \
                        "stop" if current_action in ("pillar", "pillar_bridge") else \
                        "bridge"
            walk_start_y = feet_y if nav_state == "walk" else None
            stall_count = 0

    elif nav_state == "walk":
        if walk_start_y is not None and feet_y > walk_start_y + _DEVIATE_Y:
            print(f"[deviate] fell off path feet_y={feet_y} start_y={walk_start_y}, reset")
            controller._post_control({})
            nav_state = "idle"
            path_plan = []
        elif (target_wx - pcx) * sign <= 0:
            path_idx += 1
            nav_state = "idle"
        else:
            controller._post_control({direction: True})

    elif nav_state == "stop":
        if abs(p.velocity[0]) < 0.5:
            nav_state = "pillar"
        else:
            controller._post_control({})

    elif nav_state == "pillar":
        overhead = any(
            tw.tile_at(pcx + c, head_y - dy) is not None and tw.tile_at(pcx + c, head_y - dy).solid
            and not tw.tile_at(pcx + c, head_y - dy).platform
            for c in range(2) for dy in range(1, 8)
        )
        if overhead:
            back = "left" if direction == "right" else "right"
            frames = _load_skill_frames("bridge_right_2")
            if back == "left":
                frames = [_mirror_frame(f) for f in frames]
            controller.replay_skill(frames)
            time.sleep(len(frames) / 60.0)
        else:
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
            path_idx += 1
            nav_state = "idle"
