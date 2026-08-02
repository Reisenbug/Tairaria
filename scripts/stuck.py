#!/usr/bin/env python3
"""Read a stuck snapshot and show why the planner had no way out — offline, with the game closed.

The mod writes one of these each time a loop is detected (TerraBlindLogs/stuck/). It carries the things
jump_trace.log could never show: H at every cell around, not just the ones already stood on; the candidates the
planner was choosing between; and the accumulated edge penalties, which are the hidden state that makes a loop
impossible to reproduce by replaying the same route.

    python3 stuck.py              # newest snapshot
    python3 stuck.py <file>
"""
import json, sys, glob, os

LOG = os.path.expanduser("~/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/stuck")


def load(path=None):
    if path is None:
        files = sorted(glob.glob(os.path.join(LOG, "*.json")), key=os.path.getmtime)
        if not files:
            sys.exit(f"no snapshots in {LOG}")
        path = files[-1]
    with open(path) as f:
        return path, json.load(f)


def main():
    path, s = load(sys.argv[1] if len(sys.argv) > 1 else None)
    at = tuple(s["at"])
    print(f"{os.path.basename(path)}   stuck at {at} H={s['h']}   goal={s['goal']}")
    print(f"why: {s['why']}\n")

    cells = {(c["x"], c["y"]): c for c in s["cells"]}
    x0, y0, x1, y1 = s["region"]

    # H map. A loop is a shape in this grid: the walls are cells with no H (unreachable by the field) and the
    # trap is a basin of high H with the low-H exit outside it.
    print("H field   ( ) = can stand, ### = solid & no H, ... = no H")
    print("      " + "".join(f"{x % 100:>5}" for x in range(x0, x1 + 1)))
    for y in range(y0, y1 + 1):
        row = ""
        for x in range(x0, x1 + 1):
            c = cells.get((x, y))
            if c is None:
                row += "    ."
            elif c["h"] is None:
                row += "  ###" if c["t"] is not None else "    ."
            else:
                row += f"{('(%d)' % c['h']) if c['s'] else str(c['h']):>5}"
        mark = "  <== HERE" if y == at[1] else ""
        print(f"{y:>5} {row}{mark}")

    # what it could have done, cheapest first — and whether anything led out of the basin at all
    cands = s.get("cands") or []
    print(f"\ncandidates: {len(cands)}")
    down = [c for c in cands if c["down"]]
    print(f"  descending: {len(down)}   rising: {len(cands) - len(down)}")
    seen = set()
    uniq = []
    for c in sorted(cands, key=lambda c: c["h"]):
        k = (c["x"], c["y"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(c)
    print("\n  distinct landings, lowest H first:")
    for c in uniq[:15]:
        print(f"    {c['kind']:<7} ({c['x']},{c['y']}) H={c['h']:<5} g={c['g']:<5} {'DOWN' if c['down'] else ''}")

    # penalties: an edge charged hundreds is one the planner will not take, however good it is
    pen = s.get("pen") or []
    if pen:
        pen.sort(key=lambda p: -p["p"])
        print(f"\npenalised edges in region: {len(pen)}  (top 12)")
        for p in pen[:12]:
            f, t = tuple(p["from"]), tuple(p["to"])
            fh = cells.get(f, {}).get("h")
            th = cells.get(t, {}).get("h")
            note = ""
            if fh is not None and th is not None and th < fh:
                note = "   <-- DESCENDING edge, penalised"
            print(f"    {f} -> {t}  +{p['p']}   H {fh}->{th}{note}")

    # the one question that matters: is there an exit the field can see at all?
    reach = [c for c in s["cells"] if c["h"] is not None and c["s"]]
    if reach:
        best = min(reach, key=lambda c: c["h"])
        print(f"\nlowest standable H in view: ({best['x']},{best['y']}) H={best['h']}  (here: {s['h']})")
        if best["h"] >= s["h"]:
            print("  -> nothing around is closer to the goal: the exit needs H to RISE first.")


if __name__ == "__main__":
    main()
