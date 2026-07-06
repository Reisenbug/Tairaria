import sys, os, json, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient, _jump_envelope
from terraria_agent.models.game_state import MovementInfo

_BASE = "http://127.0.0.1:17878"

def _get(path):
    resp = urllib.request.urlopen(_BASE + path, timeout=2)
    return json.loads(resp.read())

state = TerraBlindClient().detect(frame=None)
mv = state.movement

mod = _get("/jump_envelope")
py_env = _jump_envelope(mv, max_cols=32)

print(f"{'col':>4}  {'mod':>6}  {'python':>6}  {'diff':>6}")
print("-" * 30)
for i, (m, p) in enumerate(zip(mod["envelope"], py_env)):
    diff = m - p
    flag = " <--" if abs(diff) >= 2 else ""
    print(f"{i:>4}  {m:>6}  {p:>6}  {diff:>+6}{flag}")

print()
print(f"mod    js={mod['jump_speed']}  jh={mod['jump_height']}  grav={mod['gravity']}  vx={mod['vx']}")
print(f"python js={mv.jump_speed}  jh={mv.jump_height}  grav={mv.gravity}  vx={max(mv.max_run_speed, mv.acc_run_speed)}")
