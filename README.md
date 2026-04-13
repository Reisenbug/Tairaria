# Terraria Agent

An autonomous AI agent that plays Terraria, powered by a four-layer architecture inspired by the human nervous system.

## Architecture

```
Brain (LLM)          — high-level planning, goal decomposition        (~0.1 Hz)
Spinal Cord (BT)     — behavior trees for reactive decision-making    (~10 Hz)
Cerebellum (Percept) — game state perception via TerraBlind mod       (~10 Hz)
Hand (Input)         — keyboard/mouse control via pyautogui           (~10 Hz)
```

- **Brain**: An LLM planner that decomposes high-level goals (e.g. "go to jungle and collect resources") into prioritized tasks.
- **Spinal Cord**: A behavior tree engine with priority selectors for survival, combat, terrain handling, and task execution. Combat runs in parallel with movement so the agent can fight while walking.
- **Cerebellum**: Reads game state from the [TerraBlind](https://github.com/Reisenbug/TerraBlind) tModLoader mod over HTTP. Includes a 120x80 RLE tile window, object detection, enemy tracking, dropped items, inventory, buffs, and movement capabilities.
- **Hand**: Translates game actions into keyboard/mouse input. Handles key alias translation (e.g. `leftctrl` -> `ctrlleft` for pyautogui), window activation via AppKit, and hotbar management.

## Game State Perception

Instead of screen capture + computer vision, the agent uses the **TerraBlind** mod which exposes full game state over a local HTTP server (`http://127.0.0.1:17878`). This provides:

- Player position, velocity, HP, mana, buffs, debuffs
- Full inventory with item stats (damage, pick power, axe power, etc.)
- 120x80 tile window around the player (RLE compressed, with solid/liquid flags)
- World objects (chests, trees, workbenches, furnaces, etc.)
- Enemy positions, HP, boss status
- Town NPCs
- Dropped items
- Movement capabilities (jump speed, gravity, wing time, extra jumps)
- Equipment state (smart cursor, chest open, inventory open)

## Terrain Scanning

The agent scans tiles ahead in the player's facing direction to detect:

| Terrain | Detection | Response |
|---------|-----------|----------|
| **Pit** | Depth > jumpable height | Bridge with platforms or jump |
| **Block Wall** | Solid tiles at body level | Jump if low enough, mine if has pickaxe |
| **Water** | Water liquid flag | Swim through (move + jump) |
| **Lava** | Lava liquid flag | Avoid / bridge |

Jump height is calculated from the player's actual movement capabilities (base 7 tiles + extra jumps + wings).

## Behavior Tree Structure

```
ROOT [PrioritySelector]
├── SURVIVAL        — hp < 20%: potion / dodge / signal brain
├── LOW_HEALTH      — hp < 50%: potion
├── THREAT_RESPONSE — urgent projectile dodge
└── ACTIVE [Parallel]
    ├── Always(COMBAT)   — attack nearby enemies
    └── MOVE [PrioritySelector]
        ├── TERRAIN      — handle pit / wall / water / dark
        ├── TASK_EXECUTOR — execute Brain's task queue
        └── IDLE
```

## Requirements

- Python 3.11+
- macOS (uses AppKit for window activation, pyautogui for input)
- Terraria with tModLoader
- [TerraBlind](https://github.com/Reisenbug/TerraBlind) mod installed and enabled

## Installation

```bash
pip install -e ".[dev]"
```

## Usage

```bash
terraria-agent
```

Make sure Terraria is running with the TerraBlind mod loaded before starting the agent.

## Project Structure

```
src/terraria_agent/
├── brain/           — LLM planner
├── cerebellum/      — perception (TerraBlind client, damage detection)
├── hand/            — input control (keymap, hotbar organizer)
├── hud/             — debug overlay (DearPyGui)
├── models/          — data models (game state, actions, task queue)
├── orchestrator/    — main agent loop
└── spinal_cord/     — behavior trees
    ├── actions/     — movement, combat, interaction, survival, crafting
    ├── bt/          — BT engine (composites, decorators, leaves)
    ├── conditions/  — environment, health, inventory, combat checks
    └── trees/       — root, survival, combat, exploration, task executor
```

## License

See [LICENSE](LICENSE).
