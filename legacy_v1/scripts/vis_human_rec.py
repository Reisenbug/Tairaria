#!/usr/bin/env python3
"""Plot a recorded human navigation run from human_rec.json.

Renders the player trajectory (walk vs jump colored), placement tiles, and
terrain context, so the recorded "human pathfinding" can be inspected offline.
"""
import json
import os
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

PW, PH = 20, 42  # player box px

LOG = os.path.expanduser(
    "~/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/human_rec.json"
)
OUT = os.path.expanduser(
    "~/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/human_rec.png"
)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else LOG
    with open(path) as f:
        d = json.load(f)

    frames = d["frames"]
    if not frames:
        print("no frames")
        return

    # trajectory: feet-center tile coords
    xs = [(fr["px"] + PW / 2) / 16 for fr in frames]
    ys = [(fr["py"] + PH) / 16 for fr in frames]
    jump = [fr.get("jump", False) for fr in frames]

    minX, maxX = min(xs) - 4, max(xs) + 4
    minY, maxY = min(ys) - 4, max(ys) + 4
    fig, ax = plt.subplots(figsize=(max(8, (maxX - minX) * 0.3), max(6, (maxY - minY) * 0.3)))

    # walk segments green, jump segments orange
    for i in range(1, len(xs)):
        c = "#f80" if jump[i] else "#0a0"
        ax.plot([xs[i - 1], xs[i]], [ys[i - 1], ys[i]], "-", color=c, lw=1.2)
    ax.plot(xs, ys, ".", color="#060", ms=2)

    for x, y in d.get("placed", []):
        ax.add_patch(Rectangle((x, y), 1, 1, facecolor="none", edgecolor="#a0f", lw=2))

    ax.plot(xs[0], ys[0], "o", color="white", mec="black", ms=10, label="start")
    ax.plot(xs[-1], ys[-1], "*", color="red", ms=16, label="end")

    ax.set_xlim(minX, maxX)
    ax.set_ylim(maxY, minY)  # y down
    ax.set_aspect("equal")
    ax.set_title(f"human rec: {len(frames)} frames, {len(d.get('placed', []))} placements")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, lw=0.2, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT, dpi=110)
    print(OUT)


if __name__ == "__main__":
    main()
