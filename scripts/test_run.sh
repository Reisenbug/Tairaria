#!/bin/bash
# Usage: test_run.sh [seconds=10]
SECS=${1:-10}
LOG="$HOME/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/nav_events.jsonl"
TLOG="$HOME/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/jump_trace.log"
MAP_LOG="$HOME/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/ascii_map.log"
> "$LOG"; > "$TLOG"; > "$MAP_LOG"
cd "$(dirname "$0")/.."
no_proxy=127.0.0.1 python -u scripts/exec_astar.py &
PID=$!
sleep "$SECS"
no_proxy=127.0.0.1 python -c "import urllib.request; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:17878/nav_stop', data=b'{}', method='POST'))"
kill $PID 2>/dev/null; wait $PID 2>/dev/null
echo "=== plans ==="
grep '"plan_done"\|"plan_failed"' "$LOG" | python3 -c "
import sys,json
for l in sys.stdin:
    try:
        r=json.loads(l)
        actions=[n['action'] for n in r.get('path',[])]
        print(f'e={r[\"e\"]} goal={r.get(\"goal\")} pillars={actions.count(\"pillar\")} jumps={actions.count(\"jump\")} reason={r.get(\"reason\",\"\")}')
    except: pass
" | head -10
echo "=== fails ==="
grep '"nav_failed"' "$LOG" | python3 -c "
import sys,json
from collections import Counter
reasons=[]
for l in sys.stdin:
    try: reasons.append(json.loads(l)['reason'])
    except: pass
print(Counter(reasons))
"
echo "=== first map ==="
head -22 "$MAP_LOG"
