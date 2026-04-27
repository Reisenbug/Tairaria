# Terraria Agent

An autonomous AI agent that plays Terraria, powered by a four-layer architecture inspired by the human nervous system.

## Architecture

```
Brain (LLM)          — high-level strategy, skill selection        (~0.1 Hz)
Spinal Cord (BT)     — reflex safety net (HP, cave detection)      (~5 Hz)
Cerebellum (Percept) — game state via TerraBlind mod HTTP          (~5 Hz)
Hand (Mod)           — all input via /control, /replay, /fight     (60 Hz)
```

- **Brain**: LLM planner (Dashscope API) that selects skills and durations based on game state.
- **Spinal Cord**: Lightweight BT for reflexes only — HP potions, cave bypass, default walk.
- **Cerebellum**: Reads game state from the [TerraBlind](https://github.com/Reisenbug/TerraBlind) mod over HTTP at `:17878`.
- **Hand**: All input goes through the mod, not pyautogui. The mod runs at 60fps and handles precise timing.

## Input Architecture

All game input is mod-side (no pyautogui mouse control):

| Endpoint | Purpose |
|----------|---------|
| `/control` | Movement (WASD), jump, item use, slot selection, mouse aim (mx/my) |
| `/replay` | Frame-by-frame skill playback at 60fps |
| `/fight` | Auto-aim + attack nearest enemy at 60fps |
| `/walk_to_edge` | Walk until overhead clears, then stop |
| `/place` | Place a tile at relative coordinates |
| `/interact` | Right-click a tile |
| `/loot_all` | Pick up all nearby items |
| `/quick_heal` | Use a potion |

Mouse aim in `/control` and `/replay` uses tile offsets relative to the player center (`mx`, `my`), not screen coordinates.

## Game State Perception

The **TerraBlind** mod exposes full game state over HTTP:

- Player position, velocity, HP, mana, buffs, selected slot
- Full inventory with item stats (damage, ammo type, weapon/tool/ammo classification)
- 120×80 RLE tile window around the player
- World objects (chests, trees, workbenches, etc.)
- Enemy positions, HP, boss status, screen coordinates (`sx`, `sy`)
- Dropped items, town NPCs
- Walk-to-edge completion flag

## Skill System

Skills are recorded JSON files in `skills/`. Each skill captures exact frame inputs at 60fps with repeat-frame compression:

```json
{
  "smart_cursor": false,
  "frames": [
    {"jump": true, "right": true, "slot": 2, "mx": 1.2, "my": -0.5, "repeat": 8},
    ...
  ]
}
```

Current skills: `cave_bypass_left`, `cave_bypass_right`, `pillar_jump_2_height`, `rail_accelerate_*`

### Recording a skill

```bash
python scripts/record_action.py <skill_name>
# P to replay, Q to save and quit
```

### Trimming idle frames

```bash
python scripts/trim_skill.py              # all skills
python scripts/trim_skill.py skills/foo.json  # specific file
python scripts/trim_skill.py --dry-run    # preview only
```

## Cave Bypass

When the agent detects an overhead cave while walking:

1. Mod walks player to cave edge (`/walk_to_edge`)
2. Python polls `/state` for `walk_to_edge_done`
3. Replays `skills/cave_bypass_{dir}.json` via `/replay`

## Combat

`/fight` starts mod-side autonomous combat:
- Finds nearest enemy within `max_dist` tiles every frame
- Selects first weapon slot (excludes ammo: `item.ammo == AmmoID.None`)
- Sets `Main.mouseX/Y` and `controlUseItem` at 60fps
- Auto-renews while targets exist; times out 6s after last target lost

## Requirements

- Python 3.11+
- macOS
- Terraria with tModLoader
- [TerraBlind](https://github.com/Reisenbug/TerraBlind) mod installed and enabled
- Dashscope API key (for LLM)

## Installation

```bash
pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and fill in your API key.

## Usage

```bash
terraria-agent
```

### Test scripts

```bash
python scripts/test_fight.py          # combat test
python scripts/test_cave_bypass_left.py  # cave bypass test
python scripts/debug_state.py         # print live game state
```

## Project Structure

```
src/terraria_agent/
├── agent.py             — main agent loop (LLM + BT + cave + fight)
├── cave_detector.py     — overhead cave detection
├── cerebellum/          — TerraBlind HTTP client
├── geometry.py          — world↔tile coordinate helpers
├── hand/
│   └── mod_controller.py — all mod HTTP endpoints
├── llm_client.py        — Dashscope LLM wrapper
├── models/              — game state, actions, task queue
├── skill_registry.py    — skill name → ctrl dict mapping
├── spinal_cord/         — BT engine and reflex actions
└── state_serializer.py  — game state → LLM prompt text

skills/                  — recorded skill JSON files
scripts/                 — test and utility scripts
```

## License

See [LICENSE](LICENSE).
