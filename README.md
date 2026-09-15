# Terraria Agent

An AI that plays Terraria. Pathfinding, building and combat are implemented as primitives inside
a tModLoader mod ([TerraBlind](https://github.com/Reisenbug/TerraBlind)); an LLM sits on top and
drives them as tools, talking to the player through in-game chat.

The original design -- a four-layer Python stack reading the screen with YOLO -- is archived in
`legacy_v1/`. See [VISION.md](VISION.md) for that framing and [why it changed](#how-this-differs-from-v1).

## Where the code lives

Most of the system is the mod, not this repo.

```
TerraBlind mod (C#)   ~100 files: perception, pathfinding, building, combat, full-run orchestration
  └─ HTTP :17878      ~150 endpoints, the entire interface
scripts/second_player.py   the LLM agent: tool-calling loop over those endpoints
legacy_v1/            archived v1 (Python four-layer stack), not runnable, kept for reference
```

Mod source (not in this repo):
`~/Library/Application Support/Terraria/tModLoader/ModSources/TerraBlind/`

Its `CAPABILITIES.md` is the authoritative list of primitives. **Read it before building anything
new**, since most things already exist.

## Two ways to run

### 1. Scripted full run, no LLM

The whole pipeline lives in the mod (`Flow/StartRun.cs`) and runs without Python at all:

```
/start        collect torches -> pick a house site -> walk there -> build -> descend -> hell
/halt         emergency stop: kills the pipeline and every running action
/vis          toggle the debug overlay
```

Phases are `Torch -> Site -> GotoSite -> House -> Descend -> Hell`. Any failure stops the run and
reports a reason rather than continuing blind. Wood is assumed stocked (9999), so there is no
tree-chopping phase.

### 2. LLM second player

`scripts/second_player.py` is an agent that plays *alongside* you. You type `/tb <goal>` in chat;
it plans the goal once, executes it itself, and replans only on failure. It can ask you a question
mid-task and **block** on your reply (your next `/tb`), then continue the same task. It is not
one-shot per message.

```bash
python scripts/second_player.py
```

Tools exposed to the model: `get_state` `find_tiles` `find_biome` `find_descent` `descent_route`
`nav_to` `mine` `act` `interact` `use_item` `craft` `recipe` `item_info` `tile_names` `loot_all`
`fight` `jungle` `wiki_search` `wiki_page` `say` `ask`.

`/tb 2` teleports to hell and runs that stage alone, for testing that segment in isolation.
There is no `/tb 1`: the full run is the mod's own `/start`, described above.

## How the mod pathfinds

Walking, jumping, mining and platform-placing are all priced in **frames**, using a physics engine
reconstructed from the game's source. Each step simulates every action and picks the one whose
landing lands closest to the goal for the least cost. Greedy drives the route; A\* takes over the
moment it gets stuck.

Consequences worth knowing:
- `/nav_recede` has a **24px (1.5 tile) tolerance**: stopping in the neighbouring column counts as
  arrival. If you need exact positioning, follow it with `/settle {col}`.
- Every primitive's termination test reads **world facts** (is the tile there, are the feet on
  ground), never a frame count.
- Async primitives follow one shape: `POST /x` -> `{accepted}`, poll `/x_status` -> `{outcome}`,
  abort with `/x_stop`.

## Requirements

- Python 3.11+, macOS
- Terraria + tModLoader with the TerraBlind mod built and enabled
- [DragonLens](https://steamcommunity.com/sharedfiles/filedetails/?id=2807869729), used to disable
  spawns / toggle godmode / fast-forward
- An OpenAI-compatible API endpoint (only for the LLM second player)

## Setup

```bash
pip install openai python-dotenv websockets
```

Then create `.env`:

```
SECOND_PLAYER_API_URL=https://api.openai.com/v1
SECOND_PLAYER_MODEL=gpt-4o
SECOND_PLAYER_API_KEY=your-api-key-here
SECOND_PLAYER_RPM=20
```

`COMMANDER_*` is accepted as a fallback for each of these.

> **Packaging is currently stale.** `pyproject.toml` still declares a `terraria-agent` console
> script pointing at `src/terraria_agent/`, which now only exists under `legacy_v1/`, so
> `pip install -e .` and the `terraria-agent` command do not work. It also declares `pyautogui` and
> `pydantic` (unused by the live script) and omits `websockets` (required). Install the three
> packages directly, as above, until this is cleaned up.

## Debugging

`scripts/` holds only the agent now. The older helper scripts (`stuck.py`, `house_site.py`,
`house_map.py`, `foundation.py`) moved to `legacy_v1/scripts/`: the house ones were superseded by
the mod's `HouseBuilder` / `scan_house`, and `stuck.py` reads a snapshot format the mod still
writes, so it can be pulled back out if pathfinding loops need it.

Main log:
```
~/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/jump_trace.log
```

## How this differs from v1

| | v1 (`legacy_v1/`) | now |
|---|---|---|
| Perception | YOLO on screenshots | mod reads game state directly |
| Input | pyautogui | mod HTTP, 60fps mod-side |
| Tactics | behaviour tree in Python | primitives in C#, LLM plans over them |
| Orchestration | Python loop, HTTP round-trip per step | inside the mod (`StartRun.cs`) |

The move was driven by timing: a Python loop at ~5 Hz cannot make jump decisions, and every
orchestration step paid an HTTP round-trip. Python decides *what* to do; the mod decides *when*.

## License

See [LICENSE](LICENSE).
