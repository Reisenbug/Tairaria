"""Test: /place active + 5 consecutive /control jumps.
Simulates PillarJump fully. If peak_vy stays ~-4.6 for all 5 → jump path fine,
bot bug is elsewhere (e.g. cave detection). If only first jumps → /place blocks jump.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

CONTROL_URL = "http://127.0.0.1:17878/control"
PLACE_URL = "http://127.0.0.1:17878/place"
PLACE_STOP_URL = "http://127.0.0.1:17878/place_stop"
STATE_URL = "http://127.0.0.1:17878/state"

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def post(url: str, payload: dict) -> None:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with opener.open(req, timeout=0.5) as resp:
        resp.read()


def get_state() -> dict:
    with opener.open(STATE_URL, timeout=0.5) as resp:
        return json.loads(resp.read())


def find_platform_slot(state: dict) -> int | None:
    for i, s in enumerate(state.get("equipment", {}).get("hotbar", [])):
        if s.get("category") == "platform" and s.get("stack", 0) > 0:
            return i
    return None


def one_jump(label: str, hold_ticks: int = 6, rest_ticks: int = 10, tick_ms: int = 50) -> None:
    s0 = get_state()
    y0 = s0["player"]["pos"]["y"]
    vy0 = s0["player"]["vel"]["y"]
    print(f"  [{label}] start y={y0:.1f} vy={vy0:.2f}")

    peak_vy = 0.0
    for i in range(hold_ticks):
        post(CONTROL_URL, {"jump": True})
        time.sleep(tick_ms / 1000.0)
        vy = get_state()["player"]["vel"]["y"]
        if vy < peak_vy:
            peak_vy = vy

    for i in range(rest_ticks):
        post(CONTROL_URL, {})
        time.sleep(tick_ms / 1000.0)

    s1 = get_state()
    y1 = s1["player"]["pos"]["y"]
    vy1 = s1["player"]["vel"]["y"]
    print(f"  [{label}] peak_vy={peak_vy:.2f} end y={y1:.1f} vy={vy1:.2f} dy={y1-y0:.1f}")


def main() -> None:
    print("Stand on flat ground. Need platform in hotbar. Starting in 3s...")
    time.sleep(3)

    slot = find_platform_slot(get_state())
    if slot is None:
        print("ERROR: no platform in hotbar")
        return
    print(f"platform slot={slot}")

    total_frames = 5 * (6 + 10) * 3
    post(PLACE_URL, {"dx": 1, "dy": 0, "slot": slot, "duration_frames": total_frames})
    print(f"/place started ({total_frames} frames)")

    try:
        for i in range(5):
            one_jump(f"jump{i+1}")
            time.sleep(0.3)
    finally:
        post(PLACE_STOP_URL, {})
        print("/place_stop sent")


if __name__ == "__main__":
    sys.exit(main() or 0)
