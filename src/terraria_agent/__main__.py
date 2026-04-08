from __future__ import annotations

import os


def main() -> None:
    from terraria_agent.hud.app import run_hud
    from terraria_agent.hud.state_bridge import StateBridge
    from terraria_agent.orchestrator.agent_loop import AgentOrchestrator

    bridge = StateBridge()

    detector = None
    source = os.environ.get("TERRARIA_AGENT_DETECTOR", "terra_blind").lower()
    if source == "terra_blind":
        from terraria_agent.cerebellum.terra_blind_client import TerraBlindClient
        detector = TerraBlindClient()

    orchestrator = AgentOrchestrator(bridge, tick_rate=5.0, detector=detector)
    orchestrator.start()
    try:
        run_hud(bridge)
    finally:
        orchestrator.stop()


if __name__ == "__main__":
    main()
