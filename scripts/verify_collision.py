#!/usr/bin/env python3
"""
Pairs edge_emit and edge_actual from jump_trace.log and classifies mismatches.

Categories:
  predicate_disagreement  - arc_clips != (ceil_frames > 0) in emit
  planner_optimistic_ceil - planner ceil_frames==0, actual ceil_frames > 0
  planner_optimistic_wall - wall contact in both, actual landing offset > 1 tile
  wall_contact_benign     - wall contact in both, landing matches (legal wall slide)
  landing_mismatch_pure   - no wall/ceil contact, landing offset > 1 tile
  never_executed          - emit exists, no matching actual

Usage: python scripts/verify_collision.py [logfile]
"""

import sys
import re
from collections import defaultdict

LOG = sys.argv[1] if len(sys.argv) > 1 else \
    "/Users/lhy/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/jump_trace.log"

def parse_emit(line):
    m = re.search(r'edge_emit type=jump from=\((\d+),(\d+)\) to=\((\d+),(\d+)\) hold=(\d+) startVx=(-?[\d.]+) wall_frames=(\d+) ceil_frames=(\d+) tick=(\d+)', line)
    if not m: return None
    return {
        'from': (int(m[1]), int(m[2])),
        'to':   (int(m[3]), int(m[4])),
        'hold': int(m[5]),
        'startVx': float(m[6]),
        'wall_frames': int(m[7]),
        'ceil_frames': int(m[8]),
        'tick': int(m[9]),
    }

def parse_actual(line):
    m = re.search(r'edge_actual type=jump from=\((\d+),(\d+)\) to=\((\d+),(\d+)\) actual_landing=\((\d+),(\d+)\) wall_frames=(\d+) ceil_frames=(\d+) tick=(\d+)', line)
    if not m: return None
    return {
        'from': (int(m[1]), int(m[2])),
        'to':   (int(m[3]), int(m[4])),
        'actual_landing': (int(m[5]), int(m[6])),
        'wall_frames': int(m[7]),
        'ceil_frames': int(m[8]),
        'tick': int(m[9]),
    }

emits = []
actuals = []
with open(LOG) as f:
    for line in f:
        e = parse_emit(line)
        if e: emits.append(e)
        a = parse_actual(line)
        if a: actuals.append(a)

print(f"Parsed: {len(emits)} emits, {len(actuals)} actuals")

# pair by (from, to), nearest tick
actual_by_key = defaultdict(list)
for a in actuals:
    actual_by_key[(a['from'], a['to'])].append(a)

counts = defaultdict(int)
samples = defaultdict(list)

for e in emits:
    key = (e['from'], e['to'])
    candidates = actual_by_key.get(key, [])
    # pick closest actual after emit tick
    candidates_after = [a for a in candidates if a['tick'] >= e['tick']]
    if not candidates_after:
        counts['never_executed'] += 1
        samples['never_executed'].append(e)
        continue

    a = min(candidates_after, key=lambda x: x['tick'] - e['tick'])
    dx = abs(a['actual_landing'][0] - e['to'][0])
    dy = abs(a['actual_landing'][1] - e['to'][1])
    landing_ok = dx <= 1 and dy <= 1

    sim_ceil = e['ceil_frames'] > 0
    act_ceil = a['ceil_frames'] > 0
    sim_wall = e['wall_frames'] > 0
    act_wall = a['wall_frames'] > 0

    record = {'emit': e, 'actual': a, 'dx': dx, 'dy': dy}

    if sim_ceil != act_ceil and not sim_ceil and act_ceil:
        counts['planner_optimistic_ceil'] += 1
        samples['planner_optimistic_ceil'].append(record)
    elif sim_wall and act_wall and not landing_ok:
        counts['planner_optimistic_wall'] += 1
        samples['planner_optimistic_wall'].append(record)
    elif sim_wall and act_wall and landing_ok:
        counts['wall_contact_benign'] += 1
        samples['wall_contact_benign'].append(record)
    elif not sim_wall and not act_wall and not sim_ceil and not act_ceil and not landing_ok:
        counts['landing_mismatch_pure'] += 1
        samples['landing_mismatch_pure'].append(record)

    # predicate disagreement: arc_clips is always False in emit (filtered out before emit)
    # so check sim ceil_frames vs actual ceil_frames disagreement broadly
    if sim_ceil != act_ceil:
        counts['predicate_disagreement'] += 1
        samples['predicate_disagreement'].append(record)

print()
categories = ['predicate_disagreement', 'planner_optimistic_ceil', 'planner_optimistic_wall',
              'wall_contact_benign', 'landing_mismatch_pure', 'never_executed']
mismatch_total = sum(counts[c] for c in categories if c != 'wall_contact_benign' and c != 'never_executed')
print(f"{'Category':<30} {'Count':>6}")
print("-" * 38)
for c in categories:
    marker = "  (observe only)" if c == 'wall_contact_benign' else ""
    print(f"  {c:<28} {counts[c]:>6}{marker}")
print(f"{'Mismatch total (excl benign)':<30} {mismatch_total:>6}")

print()
for cat in ['planner_optimistic_ceil', 'planner_optimistic_wall', 'landing_mismatch_pure', 'predicate_disagreement']:
    shown = samples[cat][:3]
    if not shown: continue
    print(f"=== {cat} (top {len(shown)}) ===")
    for r in shown:
        e, a = r['emit'], r['actual']
        print(f"  emit:   from={e['from']} to={e['to']} hold={e['hold']} startVx={e['startVx']} wall={e['wall_frames']} ceil={e['ceil_frames']} tick={e['tick']}")
        print(f"  actual: from={a['from']} to={a['to']} landed={a['actual_landing']} wall={a['wall_frames']} ceil={a['ceil_frames']} tick={a['tick']} dx={r['dx']} dy={r['dy']}")
    print()
