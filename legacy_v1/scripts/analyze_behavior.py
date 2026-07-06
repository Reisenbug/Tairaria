import sys, os, json, math
from collections import defaultdict

DEFAULT_LOG = os.path.expanduser(
    "~/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/nav_events.jsonl"
)

def load_events(path):
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                pass
    return events

def stats(vals):
    if not vals:
        return {"n": 0}
    n = len(vals)
    mean = sum(vals) / n
    std = math.sqrt(sum((v - mean) ** 2 for v in vals) / n) if n > 1 else 0.0
    sv = sorted(vals)
    p50 = sv[int(n * 0.5)]
    p90 = sv[min(int(n * 0.9), n - 1)]
    p99 = sv[min(int(n * 0.99), n - 1)]
    return {"n": n, "mean": mean, "std": std, "p50": p50, "p90": p90, "p99": p99, "max_abs": max(abs(v) for v in vals)}

def fmt_stats(s, field):
    if s["n"] == 0:
        return "n=0"
    return (f"n={s['n']} mean={s['mean']:+.1f} std={s['std']:.1f} "
            f"p50={s['p50']:+d} p90={s['p90']:+d} p99={s['p99']:+d} max_abs={s['max_abs']}")

def analyze_exit_deltas(events):
    by_action_mode = defaultdict(lambda: {"dx": [], "dy": []})
    for ev in events:
        if ev.get("e") != "node_exit":
            continue
        action = ev.get("action", "?")
        mode = ev.get("mode", "plain")
        key = (action, mode)
        dx = ev.get("delta_x")
        dy = ev.get("delta_y")
        if dx is not None:
            by_action_mode[key]["dx"].append(dx)
        if dy is not None:
            by_action_mode[key]["dy"].append(dy)

    lines = ["## 1. Exit Delta Statistics (by action × mode)\n"]
    for action in ["move", "jump", "fall", "bridge", "bridge_fall", "pillar"]:
        action_keys = [(a, m) for (a, m) in by_action_mode if a == action]
        if not action_keys:
            continue
        lines.append(f"### {action}")
        lines.append("| mode | axis | n | mean | std | p50 | p90 | p99 | max_abs |")
        lines.append("|------|------|---|------|-----|-----|-----|-----|---------|")
        for (a, mode) in sorted(action_keys):
            d = by_action_mode[(a, mode)]
            for axis, vals in [("dx", d["dx"]), ("dy", d["dy"])]:
                s = stats(vals)
                if s["n"] == 0:
                    continue
                lines.append(
                    f"| {mode} | {axis} | {s['n']} | {s['mean']:+.2f} | {s['std']:.2f} "
                    f"| {s['p50']:+d} | {s['p90']:+d} | {s['p99']:+d} | {s['max_abs']} |"
                )
        lines.append("")
    return "\n".join(lines)

def analyze_precondition_failures(events):
    counts = defaultdict(int)
    for ev in events:
        if ev.get("e") != "precondition_check":
            continue
        if ev.get("passed"):
            continue
        key = (ev.get("from_action", "?"), ev.get("to_action", "?"),
               ev.get("reason", "?"), ev.get("severity", "?"))
        counts[key] += 1

    lines = ["## 2. Precondition Failures\n"]
    if not counts:
        lines.append("No failures recorded.\n")
        return "\n".join(lines)
    lines.append("| from_action | to_action | reason | severity | count |")
    lines.append("|-------------|-----------|--------|----------|-------|")
    for (fa, ta, r, sev), cnt in sorted(counts.items(), key=lambda x: -x[1]):
        lines.append(f"| {fa} | {ta} | {r} | {sev} | {cnt} |")
    lines.append("")
    return "\n".join(lines)

def analyze_replan_storms(events):
    failures = [(ev.get("tick", 0), ev.get("reason", "?"))
                for ev in events if ev.get("e") == "nav_failed"]
    failures.sort()

    WINDOW = 300
    MIN_COUNT = 3
    storms = []
    i = 0
    while i < len(failures):
        t0, _ = failures[i]
        window_end = t0 + WINDOW
        j = i
        while j < len(failures) and failures[j][0] <= window_end:
            j += 1
        count = j - i
        if count >= MIN_COUNT:
            reasons = [r for _, r in failures[i:j]]
            most_common = max(set(reasons), key=reasons.count)
            storms.append((t0, failures[j - 1][0], count, most_common))
            i = j
        else:
            i += 1

    lines = ["## 3. Replan Storm Detection (window=300 ticks, threshold=3)\n"]
    if not storms:
        lines.append("No storms detected.\n")
        return "\n".join(lines)
    lines.append("| start_tick | end_tick | count | top_reason |")
    lines.append("|------------|----------|-------|------------|")
    for (t0, t1, cnt, r) in storms:
        lines.append(f"| {t0} | {t1} | {cnt} | {r} |")
    lines.append("")
    return "\n".join(lines)

def analyze_health(events):
    total_exits = sum(1 for ev in events if ev.get("e") == "node_exit")
    deviate_fails = sum(1 for ev in events if ev.get("e") == "nav_failed" and ev.get("reason") == "deviate")
    precond_aborts = sum(1 for ev in events if ev.get("e") == "nav_failed" and ev.get("reason") == "precondition_abort")
    stall_fails = sum(1 for ev in events if ev.get("e") == "nav_failed" and ev.get("reason") == "stall")
    total_fails = sum(1 for ev in events if ev.get("e") == "nav_failed")
    clean_pct = (total_exits / max(total_exits + total_fails, 1)) * 100

    total_precond = sum(1 for ev in events if ev.get("e") == "precondition_check")
    precond_pass = sum(1 for ev in events if ev.get("e") == "precondition_check" and ev.get("passed"))

    lines = ["## 4. Overall Health\n"]
    lines.append("| metric | value |")
    lines.append("|--------|-------|")
    lines.append(f"| total node_exit | {total_exits} |")
    lines.append(f"| total nav_failed | {total_fails} |")
    lines.append(f"| deviate failures | {deviate_fails} |")
    lines.append(f"| precondition_abort | {precond_aborts} |")
    lines.append(f"| stall failures | {stall_fails} |")
    lines.append(f"| clean node % | {clean_pct:.1f}% |")
    lines.append(f"| precondition checks | {total_precond} |")
    lines.append(f"| precondition pass | {precond_pass} |")
    lines.append("")
    return "\n".join(lines)

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LOG
    if not os.path.exists(path):
        print(f"Log not found: {path}")
        sys.exit(1)
    events = load_events(path)
    print(f"# Behavior Analysis Report\n")
    print(f"Log: `{path}` — {len(events)} events\n")
    print(analyze_exit_deltas(events))
    print(analyze_precondition_failures(events))
    print(analyze_replan_storms(events))
    print(analyze_health(events))

if __name__ == "__main__":
    main()
