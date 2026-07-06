"""
记录一次跳跃弧线，对比 position 实际变化和 velocity，找模拟器误差。
用法: python record_jump.py [right|left]
"""
import sys, time, json, urllib.request

HOST = "http://127.0.0.1:17878"
direction = sys.argv[1] if len(sys.argv) > 1 else "right"

def post(path, data={}):
    body = json.dumps(data).encode()
    req = urllib.request.Request(f"{HOST}{path}", data=body, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=3) as r:
        return json.loads(r.read())

def get(path):
    req = urllib.request.Request(f"{HOST}{path}", method="GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=3) as r:
        return json.loads(r.read())

# 开始录制
post("/physics_record_start")
print("Recording started")

# 发跳跃指令
payload = {"jump": True, direction: True}
post("/control", payload)
time.sleep(0.1)
post("/control", {direction: True})

# 等待落地
time.sleep(2.0)

# 停止录制
result = post("/physics_record_stop")
frames = result["frames"]
print(f"Recorded {len(frames)} frames")

# 分析：对比 px 变化和 vx
print("\nframe | vx      | dx(actual) | diff")
print("-" * 50)
for i in range(1, min(len(frames), 80)):
    f0, f1 = frames[i-1], frames[i]
    vx = f0["vx"]
    dx_actual = f1["px"] - f0["px"]
    diff = dx_actual - vx
    if abs(diff) > 0.01:
        ratio = abs(diff/vx) if vx != 0 else 0
        print(f"  {f0['f']:4d} | {vx:7.3f} | {dx_actual:10.3f} | {diff:+.3f}  {'<< LARGE' if ratio > 0.3 else ''}")

# 找起跳帧
jump_frame = next((f for f in frames if f["j"] == 1), None)
if jump_frame:
    print(f"\nJump start: frame={jump_frame['f']} px={jump_frame['px']:.2f} vx={jump_frame['vx']:.3f}")

# 找最高点
peak = min(frames, key=lambda f: f["py"])
print(f"Peak: frame={peak['f']} py={peak['py']:.2f} vy={peak['vy']:.3f}")

# 找落地帧
for i in range(1, len(frames)):
    if frames[i-1]["vy"] > 0 and frames[i]["g"] == 1:
        f = frames[i]
        print(f"Landing: frame={f['f']} px={f['px']:.2f} py={f['py']:.2f} vx={f['vx']:.3f}")
        cx = int((f['px'] + 10) / 16)
        cy = int((f['py'] + 42) / 16) - 1
        print(f"  tile: ({cx}, {cy})")
        break
