import sys, os, json, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv()

from terraria_agent.hand.mod_controller import ModController

controller = ModController()

# 木平台：1木材 → 2木平台，目标50个，需要25次
ITEM_NAME = "木平台"
AMOUNT = 50

print(f"制作 {AMOUNT} 个 {ITEM_NAME}...")
import json, urllib.request
payload = {"item_id": 94, "amount": AMOUNT}
data = json.dumps(payload).encode()
req = urllib.request.Request("http://127.0.0.1:17878/craft", data=data, method="POST")
req.add_header("Content-Type", "application/json")
try:
    with urllib.request.urlopen(req, timeout=2) as r:
        print(f"结果: {r.read().decode()}")
except urllib.request.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode()}")
