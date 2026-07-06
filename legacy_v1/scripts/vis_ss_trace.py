#!/usr/bin/env python3
"""Plot the state-space planner's planned trajectory + terrain from ss_trace.json.

Reads the mod's dump (~/Library/.../TerraBlindLogs/ss_trace.json) and renders:
  terrain (solid/platform/slope), planned trajectory (walk vs jump colored),
  placement tiles, start and goal. Saves PNG for offline inspection.
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
    "~/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/ss_trace.json"
)
OUT = os.path.expanduser(
    "~/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/ss_trace.png"
)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else LOG
    with open(path) as f:
        d = json.load(f)

    minX, minY, maxX, maxY = d["region"]
    fig, ax = plt.subplots(figsize=(max(8, (maxX - minX) * 0.25), max(6, (maxY - minY) * 0.25)))

    kind_color = {1: "#444", 2: "#b97", 3: "#777"}  # solid / platform / slope
    for x, y, k in d["tiles"]:
        ax.add_patch(Rectangle((x, y), 1, 1, color=kind_color.get(k, "#444")))

    # explored frontier (where the search actually reached)
    exp = d.get("explored", [])
    if exp:
        ax.plot([p[0] for p in exp], [p[1] for p in exp], ".", color="#39f", ms=3, alpha=0.35, label="explored")

    # planned trajectory: convert top-left px -> tile coords (center x, feet y)
    traj = d["traj"]
    xs = [(p[0] + PW / 2) / 16 for p in traj]
    ys = [(p[1] + PH) / 16 for p in traj]
    ax.plot(xs, ys, "-", color="#0c0", lw=1.0, alpha=0.8, label="planned")
    ax.plot(xs, ys, ".", color="#0a0", ms=2)

    # placement tiles
    for x, y in d.get("place", []):
        ax.add_patch(Rectangle((x, y), 1, 1, facecolor="none", edgecolor="#a0f", lw=2))

    sx, sy = d["start"]
    gx, gy = d["goal"]
    ax.plot(sx + 0.5, sy + 0.5, "o", color="white", mec="black", ms=10, label="start")
    ax.plot(gx + 0.5, gy + 0.5, "*", color="red", ms=16, label="goal")

    ax.set_xlim(minX, maxX + 1)
    ax.set_ylim(maxY + 1, minY)  # y down
    ax.set_aspect("equal")
    ax.set_title(f"found={d['found']} placements={len(d.get('place', []))} frames={len(traj)}")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, lw=0.2, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT, dpi=110)
    print(OUT)


if __name__ == "__main__":
    main()
