from __future__ import annotations


def main() -> None:
    from terraria_agent.hud.app import run_hud
    from terraria_agent.hud.state_bridge import StateBridge
    from terraria_agent.orchestrator.agent_loop import AgentOrchestrator

    bridge = StateBridge()
    orchestrator = AgentOrchestrator(bridge, tick_rate=5.0)
    orchestrator.start()
    try:
        run_hud(bridge)
    finally:
        orchestrator.stop()


if __name__ == "__main__":
    main()
