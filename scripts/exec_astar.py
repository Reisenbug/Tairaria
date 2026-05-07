import sys, os, time, json, urllib.request, signal, glob
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient

_BASE = "http://127.0.0.1:17878"
direction = "left"
sign = 1 if direction == "right" else -1

BLACKLIST_TTL = 60
MAX_BLACKLIST_SIZE = 20

perception = TerraBlindClient()
failed_goals = {}  # (gx, gy) -> expire_time
last_goal = None

_REPORT_DIR = os.path.expanduser(
    "~/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/debug_reports"
)
_seen_reports = set()


def _post_get(path, data):
    try:
        body = json.dumps(data).encode()
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


def _purge_expired():
    now = time.time()
    expired = [g for g, t in failed_goals.items() if t <= now]
    for g in expired:
        del failed_goals[g]


def _start_nav(excluded=None):
    global last_goal
    _purge_expired()
    excluded_list = list(excluded) if excluded else []
    _post_get("/nav_start", {"sign": sign, "excluded_goals": excluded_list})
    resp = _post_get("/plan_path", {"sign": sign, "excluded_goals": excluded_list})
    goal = resp.get("goal")
    if goal and resp.get("path"):
        last_goal = tuple(goal)
        print(f"[nav] start goal={last_goal} blacklist_size={len(failed_goals)}")
    else:
        last_goal = None
        print("[exec] no goal found, pausing")
        print(f"[exec] blacklist: {list(failed_goals.keys())}")
        _stop()
        sys.exit(1)


def _log_and_pause():
    print("[exec] all goals exhausted, pausing")
    print(f"[exec] blacklist: {list(failed_goals.keys())}")
    _stop()
    sys.exit(1)


def _stop():
    _post_get("/nav_stop", {})
    print("[nav] stopped")

def _handle_exit(sig, frame):
    _stop()
    sys.exit(0)

signal.signal(signal.SIGINT, _handle_exit)
signal.signal(signal.SIGTERM, _handle_exit)

print(f"[nav] starting, direction={direction}")
_start_nav()

while True:
    state = perception.detect(frame=None)
    p = state.player
    if p.hp == 0:
        time.sleep(0.2)
        continue

    data = _get("/nav_done")
    status = data.get("status", "running")

    if status == "done":
        print("[nav] done, restarting")
        failed_goals.clear()
        _start_nav()
        time.sleep(0.5)
    elif status == "failed":
        reason = data.get("reason", "")
        print(f"[nav] failed: {reason}")
        if last_goal:
            failed_goals[last_goal] = time.time() + BLACKLIST_TTL
        if len(failed_goals) >= MAX_BLACKLIST_SIZE:
            _log_and_pause()
        time.sleep(0.5)
        _start_nav(excluded=list(failed_goals.keys()))
    else:
        time.sleep(0.1)
    _check_reports()
