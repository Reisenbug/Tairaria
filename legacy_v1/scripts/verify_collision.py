#!/usr/bin/env python3
"""
Pairs edge_emit and edge_actual from jump_trace.log and classifies mismatches.

Jump categories:
  predicate_disagreement  - arc_clips != (ceil_frames > 0) in emit
  planner_optimistic_ceil - planner ceil_frames==0, actual ceil_frames > 0
  planner_optimistic_wall - wall contact in both, actual landing offset > 1 tile
  wall_contact_benign     - wall contact in both, landing matches (legal wall slide)
  landing_mismatch_pure   - no wall/ceil contact, landing offset > 1 tile
  never_executed          - emit exists, no matching actual

Pillar categories:
  pillar_planner_optimistic        - pillar_collide_x=true or reached_height=false
  pillar_optimistic_side_correct   - above AND left_clear=true (root cause not side blocking)
  pillar_optimistic_side_wrong     - above AND left_clear=false (should not happen; planner bug)
  pillar_legacy_would_have_picked  - success, center_only_clear=true, left_clear=true (same as old)
  pillar_new_edge_only             - success, center_only_clear=false (new logic rescued this edge)

Usage: python scripts/verify_collision.py [logfile]
"""

import sys
import re
from collections import defaultdict

LOG = sys.argv[1] if len(sys.argv) > 1 else \
    "/Users/lhy/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/jump_trace.log"

def parse_jump_emit(line):
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

def parse_jump_actual(line):
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

def parse_pillar_emit(line):
    m = re.search(r'edge_emit type=pillar from=\((\d+),(\d+)\) to=\((\d+),(\d+)\) rise=(\d+) side=(\w+) left_clear=(\w+) right_clear=(\w+) center_only_clear=(\w+) tick=(\d+)', line)
    if not m: return None
    return {
        'from': (int(m[1]), int(m[2])),
        'to':   (int(m[3]), int(m[4])),
        'rise': int(m[5]),
        'side': m[6],
        'left_clear': m[7] == 'True',
        'right_clear': m[8] == 'True',
        'center_only_clear': m[9] == 'True',
        'tick': int(m[10]),
    }

def parse_pillar_actual(line):
    m = re.search(r'edge_actual type=pillar from=\((\d+),(\d+)\) to=\((\d+),(\d+)\) actual_landing=\((\d+),(\d+)\) pillar_collide_x=(\w+) reached_height=(\w+) tick=(\d+)', line)
    if not m: return None
    return {
        'from': (int(m[1]), int(m[2])),
        'to':   (int(m[3]), int(m[4])),
        'actual_landing': (int(m[5]), int(m[6])),
        'pillar_collide_x': m[7] == 'True',
        'reached_height': m[8] == 'True',
        'tick': int(m[9]),
    }

jump_emits, jump_actuals = [], []
pillar_emits, pillar_actuals = [], []

with open(LOG) as f:
    for line in f:
        e = parse_jump_emit(line)
        if e: jump_emits.append(e)
        a = parse_jump_actual(line)
        if a: jump_actuals.append(a)
        pe = parse_pillar_emit(line)
        if pe: pillar_emits.append(pe)
        pa = parse_pillar_actual(line)
        if pa: pillar_actuals.append(pa)

print(f"Parsed: {len(jump_emits)} jump emits, {len(jump_actuals)} jump actuals")
print(f"        {len(pillar_emits)} pillar emits, {len(pillar_actuals)} pillar actuals")

# --- jump analysis ---
jump_actual_by_key = defaultdict(list)
for a in jump_actuals:
    jump_actual_by_key[(a['from'], a['to'])].append(a)

counts = defaultdict(int)
samples = defaultdict(list)

for e in jump_emits:
    key = (e['from'], e['to'])
    candidates_after = [a for a in jump_actual_by_key.get(key, []) if a['tick'] >= e['tick']]
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

    if sim_ceil != act_ceil:
        counts['predicate_disagreement'] += 1
        samples['predicate_disagreement'].append(record)

# --- pillar analysis ---
pillar_actual_by_key = defaultdict(list)
for pa in pillar_actuals:
    pillar_actual_by_key[(pa['from'], pa['to'])].append(pa)

pcounts = defaultdict(int)
psamples = defaultdict(list)
pillar_total = 0

for pe in pillar_emits:
    key = (pe['from'], pe['to'])
    candidates_after = [pa for pa in pillar_actual_by_key.get(key, []) if pa['tick'] >= pe['tick']]
    if not candidates_after:
        pcounts['pillar_never_executed'] += 1
        continue

    pa = min(candidates_after, key=lambda x: x['tick'] - pe['tick'])
    pillar_total += 1
    failed = pa['pillar_collide_x'] or not pa['reached_height']
    record = {'emit': pe, 'actual': pa}

    if failed:
        pcounts['pillar_planner_optimistic'] += 1
        psamples['pillar_planner_optimistic'].append(record)
        if pe['left_clear']:
            pcounts['pillar_optimistic_side_correct'] += 1
            psamples['pillar_optimistic_side_correct'].append(record)
        else:
            pcounts['pillar_optimistic_side_wrong'] += 1
            psamples['pillar_optimistic_side_wrong'].append(record)
    else:
        if pe['center_only_clear']:
            pcounts['pillar_legacy_would_have_picked'] += 1
        else:
            pcounts['pillar_new_edge_only'] += 1
            psamples['pillar_new_edge_only'].append(record)

# --- print jump results ---
print()
print("=== JUMP ===")
jump_categories = ['predicate_disagreement', 'planner_optimistic_ceil', 'planner_optimistic_wall',
                   'wall_contact_benign', 'landing_mismatch_pure', 'never_executed']
mismatch_total = sum(counts[c] for c in jump_categories if c not in ('wall_contact_benign', 'never_executed'))
print(f"{'Category':<35} {'Count':>6}")
print("-" * 43)
for c in jump_categories:
    marker = "  (observe only)" if c == 'wall_contact_benign' else ""
    print(f"  {c:<33} {counts[c]:>6}{marker}")
print(f"  {'Mismatch total (excl benign)':<33} {mismatch_total:>6}")

# --- print pillar results ---
print()
print("=== PILLAR ===")
pillar_categories = ['pillar_planner_optimistic', 'pillar_optimistic_side_correct',
                     'pillar_optimistic_side_wrong', 'pillar_legacy_would_have_picked',
                     'pillar_new_edge_only', 'pillar_never_executed']
print(f"{'Category':<40} {'Count':>6}")
print("-" * 48)
for c in pillar_categories:
    marker = ""
    if c == 'pillar_new_edge_only':
        marker = "  (observe only)"
    elif c == 'pillar_legacy_would_have_picked':
        marker = "  (observe only)"
    print(f"  {c:<38} {pcounts[c]:>6}{marker}")
if pillar_total > 0:
    opt_pct = pcounts['pillar_planner_optimistic'] / pillar_total * 100
    new_pct = pcounts['pillar_new_edge_only'] / pillar_total * 100
    print(f"  pillar_planner_optimistic rate: {opt_pct:.1f}%")
    print(f"  pillar_new_edge_only rate:      {new_pct:.1f}%")
    print(f"  (pillar_new_edge_only仅反映'Right-only-clear位置的出现频率'，不等于扩展SkillExecutor支持Right占位的实际收益)")

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

for cat in ['pillar_planner_optimistic', 'pillar_new_edge_only']:
    shown = psamples[cat][:3]
    if not shown: continue
    print(f"=== {cat} (top {len(shown)}) ===")
    for r in shown:
        pe, pa = r['emit'], r['actual']
        print(f"  emit:   from={pe['from']} to={pe['to']} rise={pe['rise']} side={pe['side']} left_clear={pe['left_clear']} right_clear={pe['right_clear']} center_only_clear={pe['center_only_clear']} tick={pe['tick']}")
        print(f"  actual: from={pa['from']} to={pa['to']} landed={pa['actual_landing']} collide_x={pa['pillar_collide_x']} reached={pa['reached_height']} tick={pa['tick']}")
    print()
