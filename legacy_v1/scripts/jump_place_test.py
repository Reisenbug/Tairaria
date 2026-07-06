"""
触发一次跳跃并在最高点放置平台。
用法: python scripts/jump_place_test.py [right|left]
"""
import sys
import urllib.request
import json

HOST = "http://127.0.0.1:17878"
direction = sys.argv[1] if len(sys.argv) > 1 else "right"

def post(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(f"{HOST}{path}", data=body, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=3) as r:
        return json.loads(r.read())

payload = {
    "jump": True,
    "jump_place": True,
}
if direction == "right":
    payload["right"] = True
else:
    payload["left"] = True

resp = post("/control", payload)
print(resp)
