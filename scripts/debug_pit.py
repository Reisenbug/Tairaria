import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv()

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient, _jump_peak_tiles, _jump_envelope
from terraria_agent.pit_detector import detect

perception = TerraBlindClient()

while True:
    state = perception.detect(frame=None)
    if state is None or state.player.hp == 0:
        time.sleep(0.2)
        continue

    mv = state.movement
    jump_h = _jump_peak_tiles(mv)
    jump_w = len([dy for dy in _jump_envelope(mv, max_cols=30) if dy <= 0])

    result = detect(state)
    print(f"\rjump_h={jump_h:.1f} jump_w={jump_w} | pit={result}    ", end="")
    time.sleep(0.2)
