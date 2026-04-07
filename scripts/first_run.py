"""
First real run: starts the agent with a 'walk right' default task.
Terraria must be in windowed mode and visible.

Usage:
    python scripts/first_run.py

Controls:
    - HUD shows in a separate window
    - Type 'pause' in the command box to stop movement
    - Type 'goal: walk left' then 'task: default 向左移动' to change direction
    - F12 to toggle HUD visibility
    - Close HUD window to exit
"""
from __future__ import annotations

import sys
import time

from terraria_agent.hud.state_bridge import StateBridge
from terraria_agent.models.task_queue import Task, TaskPriority, TaskQueue
from terraria_agent.orchestrator.agent_loop import AgentOrchestrator


def main() -> None:
    bridge = StateBridge()

    orch = AgentOrchestrator(bridge, tick_rate=5.0)
    orch._task_queue = TaskQueue(
        goal="walk left",
        task_queue=[
            Task(trigger="default", action="move_left", priority=TaskPriority.BASELINE),
        ],
    )

    bridge.log("[first_run] Starting — Terraria must be in windowed mode")
    bridge.log("[first_run] Player will walk left via 'a' key")
    bridge.log("[first_run] Type 'pause' in command box to stop")

    orch.start()
    time.sleep(1)

    snap = bridge.get_snapshot()
    if snap and snap.bt_status == "no-window":
        bridge.log("[first_run] WARNING: Terraria window not found!")
        print("WARNING: Terraria window not found. Make sure Terraria is running in windowed mode.")

    try:
        from terraria_agent.hud.app import run_hud
        run_hud(bridge)
    except ImportError as e:
        print(f"HUD deps not installed: {e}")
        print("Install with: pip install -e '.[hud,vision]'")
        print("Running headless instead (Ctrl+C to stop)...")
        try:
            while True:
                snap = bridge.get_snapshot()
                if snap:
                    print(
                        f"\r[tick {snap.tick_count}] hp={snap.hp}/{snap.max_hp} "
                        f"bt={snap.bt_status} branch={snap.active_bt_branch} "
                        f"actions={snap.action_buffer} keys={snap.held_keys} "
                        f"tps={snap.tps:.1f}",
                        end="",
                        flush=True,
                    )
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nStopping...")
    finally:
        orch.stop()


if __name__ == "__main__":
    main()
