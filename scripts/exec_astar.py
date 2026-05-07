import sys, os, time, json, urllib.request, signal, glob
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

_BASE = "http://127.0.0.1:17878"
direction = "right"
sign = 1 if direction == "right" else -1

_REPORT_DIR = os.path.expanduser(
    "~/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/debug_reports"
)
_seen_reports = set()


def _post(path, data=None):
    try:
        body = json.dumps(data or {}).encode()
        req = urllib.request.Request(_BASE + path, data=body, method="POST")
        resp = urllib.request.urlopen(req, timeout=2)
        return json.loads(resp.read())
    except Exception:
        return {}


def _stop():
    _post("/nav_stop")
    print("[nav] stopped")


def _handle_exit(sig, frame):
    _stop()
    sys.exit(0)


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

print(f"[nav] starting, direction={direction}")
_post("/nav_start", {"sign": sign})

while True:
    time.sleep(1)
    _check_reports()
