import sys, os, time, json, urllib.request, signal, glob
from pynput import keyboard as kb
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

_BASE = "http://127.0.0.1:17878"
direction = "right"
sign = 1 if direction == "right" else -1

_REPORT_DIR = os.path.expanduser(
    "~/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/debug_reports"
)
_MAP_LOG = os.path.expanduser(
    "~/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/ascii_map.log"
)
_seen_reports = set()
_last_event_line = 0
_frozen = False
_started = False


def _freeze():
    global _frozen
    _post("/freeze")
    _frozen = True
    state = _get("/state")
    nav = state.get("nav_state", "?")
    px, py = state.get("px", 0), state.get("py", 0)
    print(f"[debug] PAUSED  nav={nav} px={px:.1f} py={py:.1f}")


def _unfreeze():
    global _frozen
    _post("/unfreeze")
    _frozen = False
    print("[debug] RESUMED")


def _step():
    _post("/step_node")
    state = _get("/state")
    nav = state.get("nav_state", "?")
    px, py = state.get("px", 0), state.get("py", 0)
    print(f"[debug] STEP    nav={nav} px={px:.1f} py={py:.1f}")


def _on_press(key):
    global _started
    try:
        c = key.char
    except AttributeError:
        return
    if c == 'p' and not _started:
        _started = True
        print(f"[nav] starting, direction={direction}")
        _post("/nav_start", {"sign": sign})
    elif c == 'l':
        if _frozen:
            _unfreeze()
        else:
            _freeze()
    elif c == 'k' and _frozen:
        _step()


def _post(path, data=None):
    try:
        body = json.dumps(data or {}).encode()
        req = urllib.request.Request(_BASE + path, data=body, method="POST")
        resp = urllib.request.urlopen(req, timeout=2)
        return json.loads(resp.read())
    except Exception:
        return {}


def _get(path):
    try:
        resp = urllib.request.urlopen(_BASE + path, timeout=2)
        return json.loads(resp.read())
    except Exception:
        return {}


def _stop():
    _post("/nav_stop")
    print("[nav] stopped")


def _handle_exit(sig, frame):
    _stop()
    sys.exit(0)


def _render_ascii(state, goal=None):
    tiles = state.get("tiles", {})
    player = state.get("player", {})
    if not tiles or not player:
        return None

    origin_x = tiles["origin"]["x"]
    origin_y = tiles["origin"]["y"]
    rows = tiles["rows"]

    pos = player.get("pos", {})
    px = pos.get("x", 0)
    py = pos.get("y", 0)
    width = player.get("width", 20)
    height = player.get("height", 42)
    pcx = int((px + width / 2) / 16)
    feet_y = int((py + height) / 16)
    head_y = int(py / 16)

    def tile_at(wx, wy):
        dy = wy - origin_y
        if dy < 0 or dy >= len(rows):
            return None
        row = rows[dy]
        x = origin_x
        for seg in row:
            tid, flags, count = seg
            if x <= wx < x + count:
                return tid, flags
            x += count
        return None

    back, forward, up, down = 10, 40, 15, 10
    lines = []
    for drow in range(-up, down + 1):
        wy = feet_y + drow
        row_chars = []
        for dcol in range(-back, forward + 1):
            wx = pcx + sign * dcol
            if dcol == 0 and head_y <= wy <= feet_y:
                row_chars.append("P")
                continue
            if goal and wx == goal[0] and wy == goal[1]:
                row_chars.append("G")
                continue
            t = tile_at(wx, wy)
            if t is None:
                row_chars.append("?")
            else:
                tid, flags = t
                has_tile = bool(flags & 0x01)
                is_solid = bool(flags & 0x02)
                is_platform = bool(flags & 0x40)
                is_water = bool(flags & 0x04)
                is_lava = bool(flags & 0x08)
                if has_tile and is_solid:
                    row_chars.append("#")
                elif has_tile and is_platform:
                    row_chars.append("=")
                elif is_lava:
                    row_chars.append("!")
                elif is_water:
                    row_chars.append("~")
                else:
                    row_chars.append(".")
        lines.append("".join(row_chars))
    return "\n".join(lines)


def _check_events():
    global _last_event_line
    evlog = os.path.expanduser(
        "~/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/nav_events.jsonl"
    )
    if not os.path.exists(evlog):
        return
    with open(evlog) as f:
        all_lines = f.readlines()
    new_lines = all_lines[_last_event_line:]
    _last_event_line = len(all_lines)

    for line in new_lines:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        e = ev.get("e", "")
        if e in ("plan_done", "plan_failed", "nav_failed"):
            state = _get("/state")
            goal = ev.get("goal")
            ascii_map = _render_ascii(state, goal)
            if ascii_map:
                tick = ev.get("tick", "?")
                reason = ev.get("reason", "")
                header = f"[tick={tick} e={e} reason={reason} goal={goal}]"
                with open(_MAP_LOG, "a") as f:
                    f.write(header + "\n" + ascii_map + "\n\n")


def _check_reports():
    if not os.path.isdir(_REPORT_DIR):
        return
    for path in glob.glob(os.path.join(_REPORT_DIR, "*.json")):
        if path in _seen_reports:
            continue
        _seen_reports.add(path)
        try:
            with open(path) as f:
                r = json.load(f)
            tb = r.get("triggered_by", {})
            state = r.get("state", {})
            print(f"[report] {os.path.basename(path)} reason={tb.get('reason')} tick={tb.get('tick')} nav={state.get('nav_state')} px={state.get('px')},{state.get('py')}")
        except Exception as e:
            print(f"[report] failed to read {path}: {e}")


signal.signal(signal.SIGINT, _handle_exit)
signal.signal(signal.SIGTERM, _handle_exit)

open(_MAP_LOG, "w").close()

print(f"[nav] ready. press [p] to start, [l] to pause/resume, [k] to step (when paused)")
with kb.Listener(on_press=_on_press):
    while True:
        if not _frozen:
            _check_reports()
            _check_events()
            time.sleep(0.2)
        else:
            time.sleep(0.05)
