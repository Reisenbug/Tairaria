"""
测试跳跃精度：0速起跳，mod端自己找最优按键参数精确落点。
用法: python test_jump_precision.py [right|left] [dx1 dx2 ...]
"""
import sys, time, json, urllib.request

HOST = "http://127.0.0.1:17878"

def req(path, data=None, method=None):
    body = json.dumps(data).encode() if data is not None else b'{}'
    m = method or ("POST" if data is not None else "GET")
    r = urllib.request.Request(f"{HOST}{path}", data=body, method=m)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(r, timeout=5) as resp:
        return json.loads(resp.read())

def get_cx():
    s = req("/state", method="GET")
    p = s["player"]
    return int((p["pos"]["x"] + p["width"] / 2) / 16)

direction = sys.argv[1] if len(sys.argv) > 1 else "right"
sign = 1 if direction == "right" else -1
targets = [int(x) for x in sys.argv[2:]] if len(sys.argv) > 2 else list(range(1, 8))

print(f"方向: {direction}  目标格: {targets}")
print(f"{'目标dx':>6} | {'hold':>4} | {'ms':>4} | {'mf':>4} | {'sim落点':>7} | {'实际落点':>8} | {'偏差':>4} | 结果")
print("-" * 65)

for target_dx in targets:
    time.sleep(0.5)
    cx = get_cx()
    target_cx = cx + sign * target_dx

    result = req("/exec_jump_to", {"target_cx": target_cx, "sign": sign})
    if "error" in result:
        print(f"{target_dx:>6} | {result['error']}")
        continue

    sim_cx = result.get("sim_cx", -1)
    hold = result.get("hold", -1)
    ms = result.get("move_start", -1)
    mf = result.get("move_frames", -1)

    for _ in range(200):
        time.sleep(0.05)
        r = req("/exec_jump_result", method="GET")
        if r.get("done"):
            break

    actual_cx = r.get("cx", -1)
    delta = actual_cx - target_cx
    ok = "OK" if abs(delta) <= 1 else "FAIL"
    print(f"{target_dx:>6} | {hold:>4} | {ms:>4} | {mf:>4} | {sim_cx:>7} | {actual_cx:>8} | {delta:>+4} | {ok}")

    time.sleep(0.5)
