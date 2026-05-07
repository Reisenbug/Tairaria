import sys, os, time, json, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient

_BASE = "http://127.0.0.1:17878"
direction = "left"
sign = 1 if direction == "right" else -1

perception = TerraBlindClient()


def _post(path, data):
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(_BASE + path, data=body, method="POST")
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass


def _get(path):
    try:
        resp = urllib.request.urlopen(_BASE + path, timeout=2)
        return json.loads(resp.read())
    except Exception:
        return {}




def _start_nav():
    _post("/nav_start", {"sign": sign})


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
        _start_nav()
        time.sleep(0.5)
    elif status == "failed":
        reason = data.get("reason", "")
        print(f"[nav] failed: {reason}, restarting")
        time.sleep(1.0)
        _start_nav()
    else:
        time.sleep(0.1)
