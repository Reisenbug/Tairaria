import sys, os, json, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv()

with urllib.request.urlopen("http://127.0.0.1:17878/state", timeout=2) as r:
    state = json.loads(r.read())

stations = state.get("nearby_stations", [])
print(f"附近制作站: {stations}")

inv = state.get("equipment", {}).get("inventory", [])
hotbar = state.get("equipment", {}).get("hotbar", [])
all_slots = hotbar + inv
wood = [s for s in all_slots if "wood" in s.get("name", "").lower() or "木" in s.get("name", "")]
print(f"木材相关: {wood}")
