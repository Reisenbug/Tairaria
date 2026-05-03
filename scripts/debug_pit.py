import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient
from terraria_agent.pit_detector import detect
from terraria_agent.agent import print_surface_map

perception = TerraBlindClient()

while True:
    state = perception.detect(frame=None)
    if state.player.hp == 0:
        time.sleep(0.2)
        continue

    result = detect(state)
    print(f"\robstacle={result}    ", end="", flush=True)
    if result:
        print()
        print_surface_map(state)

    time.sleep(0.2)
