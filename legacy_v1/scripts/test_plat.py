"""测试 plat_up / plat_jump 放置时机。
用法:
  python test_plat.py up
  python test_plat.py up_n <n>
  python test_plat.py jump [right|left]
  python test_plat.py jump_n <n> [right|left]
"""
import sys, json, urllib.request

HOST = "http://127.0.0.1:17878"

def req(path, data=None, method=None):
    body = json.dumps(data).encode() if data is not None else b'{}'
    m = method or ("POST" if data is not None else "GET")
    r = urllib.request.Request(f"{HOST}{path}", data=body, method=m)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(r, timeout=5) as resp:
        return json.loads(resp.read())

def parse_sign(arg):
    return -1 if arg == "left" else 1

mode = sys.argv[1] if len(sys.argv) > 1 else "up"
if mode == "up":
    print(req("/test_plat_up", {}))
elif mode == "up_n":
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    print(req("/test_plat_up_n", {"n": n}))
elif mode == "jump":
    sign = parse_sign(sys.argv[2] if len(sys.argv) > 2 else "right")
    print(req("/test_plat_jump", {"sign": sign}))
elif mode == "jump_n":
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    sign = parse_sign(sys.argv[3] if len(sys.argv) > 3 else "right")
    print(req("/test_plat_jump_n", {"n": n, "sign": sign}))
else:
    print("usage: test_plat.py [up | up_n <n> | jump [right|left] | jump_n <n> [right|left]]")
