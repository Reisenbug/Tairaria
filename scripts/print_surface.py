import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient
from terraria_agent.agent import print_surface_map

perception = TerraBlindClient()
state = perception.detect(frame=None)
print_surface_map(state)
