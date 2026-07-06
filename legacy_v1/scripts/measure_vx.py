"""Measure steady-state vx: run right for 90 frames on ground, analyze last 30."""
import json, time, urllib.request, statistics

BASE = "http://127.0.0.1:17878"

def post(path, body=b"{}"):
    req = urllib.request.Request(f"{BASE}{path}", data=body, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.read().decode()

def get(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=5) as r:
        return r.read().decode()

# Start recording
post("/physics_record_start")

# Hold right for 90 frames (~1.5s) on ground
body = json.dumps({"right": True}).encode()
for _ in range(90):
    post("/control", body)
    time.sleep(1/60)

# Release
post("/control", json.dumps({}).encode())
time.sleep(0.1)

raw = post("/physics_record_stop")
data = json.loads(raw)
frames = data["frames"]

# Filter: grounded frames only, last 30 of grounded run
grounded = [f for f in frames if f["g"] == 1]
if len(grounded) < 10:
    print(f"Only {len(grounded)} grounded frames, not enough data")
else:
    vxs = [f["vx"] for f in grounded[-30:]]
    print(f"n={len(vxs)} grounded frames (last 30)")
    print(f"mean={statistics.mean(vxs):.4f}  min={min(vxs):.4f}  max={max(vxs):.4f}  stdev={statistics.stdev(vxs):.4f}")
    print("distribution:")
    buckets = {}
    for v in vxs:
        k = round(v, 2)
        buckets[k] = buckets.get(k, 0) + 1
    for k in sorted(buckets):
        print(f"  {k:.2f}: {'#'*buckets[k]} ({buckets[k]})")
