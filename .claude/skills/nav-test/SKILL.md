---
name: nav-test
description: Run a navigation test against the TerraBlind mod end-to-end. Clears jump_trace.log, dispatches a /start_seg_nav (or chosen variant) to the mod via HTTP, polls for completion, then summarizes the result. Use when the user says "test nav to X,Y" or "跑一下 navwand 到 X,Y". Has side effects on the game world; user-invocable only.
disable-model-invocation: true
---

## Inputs

Two coordinate forms accepted:
- absolute world tile: `nav-test abs <gx> <gy>` or `nav-test <gx> <gy>` if values are large
- relative to player: `nav-test rel <dx> <dy>`

Optional mode flag:
- `--mode seg` (default) — uses `/start_seg_nav` (segmented)
- `--mode normal` — uses `NavCoordinator.StartTo` via the wand-equivalent endpoint

Optional `--timeout <sec>` (default 60).

## What the skill does

1. Read player position via `GET http://127.0.0.1:17878/state`. If `rel`, compute absolute goal.
2. Truncate the log:
   ```
   > "$HOME/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/jump_trace.log"
   ```
3. POST to the mod:
   - seg: `POST /start_seg_nav {"gx":G,"gy":G}`
   - normal: `POST /start_nav_to {"gx":G,"gy":G}` (if it exists; otherwise tell user to right-click NavWand)
4. Poll `GET /state` every 0.5s, looking at player position. Stop when within 3 tiles of goal, or timeout, or seg state goes Failed.
5. Optionally call `POST /stop_seg_nav` on timeout.
6. Tail the log and grep `[seg] [nav] [loop] deviated edge_actual` from the last 800 lines. Summarize.

## Output format

```
goal: (X, Y)    mode: seg    duration: T s
result: <reached | failed | timeout>

key events:
  - tick A  [seg] plan segment to wp[0]=(...)
  - tick B  [nav] jump fire ...
  - tick C  edge_actual landing=(...) → deviated   (if any)
  - tick D  reached / [loop] / timeout

if failed: <one-line guess>
```

Don't dump the full log. Hand off to the `nav-log-analyzer` subagent if the user wants depth.

## Shell template

```bash
# truncate log
LOG="$HOME/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/jump_trace.log"
> "$LOG"

# resolve goal via Python (urllib bypasses proxy gotcha)
python3 - <<'PY'
import json, urllib.request, sys
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
# ... fetch /state, compute gx/gy, post /start_seg_nav, poll
PY

# tail key events
grep -nE "\[seg\]|\[nav\]|\[loop\]|edge_actual|deviated" "$LOG" | tail -40
```

Use Python `urllib` for HTTP — `curl` to `127.0.0.1:17878` is broken by the system proxy (documented gotcha in project memory).

## Don'ts

- Don't claim "reached" unless the polled position is within 3 tiles of goal.
- Don't loop forever. Respect timeout. On timeout, send `/stop_seg_nav` so the mod doesn't keep driving the player.
- Don't analyze the log in depth — summary only. For deep analysis spawn `nav-log-analyzer`.
