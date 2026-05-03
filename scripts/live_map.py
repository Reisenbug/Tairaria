import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient, scan_surface
from terraria_agent.pit_detector import detect

perception = TerraBlindClient()

TILE = {
    'player': '\033[92m@\033[0m',
    'surface': '\033[33m^\033[0m',
    'solid':   '\033[90m#\033[0m',
    'platform':'\033[36m=\033[0m',
    'water':   '\033[94m~\033[0m',
    'lava':    '\033[91mL\033[0m',
    'air':     ' ',
    'unknown': '?',
}

while True:
    state = perception.detect(frame=None)
    p = state.player
    tw = state.tile_window

    lines = []

    if tw is None or p.hp == 0:
        lines.append("waiting for game...")
    else:
        pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
        feet_y = int((p.pos[1] + p.height) / 16.0)
        surface = scan_surface(tw)
        obstacle = detect(state)

        status = (f"pos=({pcx},{feet_y})  hp={p.hp}/{p.max_hp}"
                  f"  dir={p.direction}  biome={state.biome}"
                  f"  obstacle={obstacle}")
        lines.append(status)
        lines.append("")

        ox, oy = tw.origin
        for ry in range(tw.height):
            wy = oy + ry
            row = f"\033[2m{wy:4d}\033[0m "
            for rx in range(tw.width):
                wx = ox + rx
                dx = wx - pcx
                dy = wy - feet_y
                if dx in (0, 1) and -2 <= dy <= 0:
                    row += TILE['player']
                elif surface.get(wx) == wy:
                    row += TILE['surface']
                else:
                    t = tw.tile_at(wx, wy)
                    if t is None:
                        row += TILE['unknown']
                    elif t.lava:
                        row += TILE['lava']
                    elif t.water:
                        row += TILE['water']
                    elif t.platform:
                        row += TILE['platform']
                    elif t.solid:
                        row += TILE['solid']
                    else:
                        row += TILE['air']
            lines.append(row)

    print("\033[H\033[2J", end="")
    print("\n".join(lines), flush=True)
    time.sleep(0.1)
