#!/usr/bin/env python3
"""Remove leading and trailing idle frames from skill JSON files."""
import json, sys
from pathlib import Path

IGNORED_KEYS = {"sc", "slot", "mx", "my", "repeat"}

def is_idle(frame: dict) -> bool:
    return all(k in IGNORED_KEYS for k in frame)

def trim(frames: list) -> list:
    start = next((i for i, f in enumerate(frames) if not is_idle(f)), None)
    if start is None:
        return []
    end = next((i for i, f in enumerate(reversed(frames)) if not is_idle(f)), None)
    return frames[start: len(frames) - end]

def process(path: Path, dry_run: bool = False) -> None:
    data = json.loads(path.read_text())
    if isinstance(data, list):
        frames = data
        wrapper = None
    else:
        frames = data["frames"]
        wrapper = data

    before = sum(f.get("repeat", 1) for f in frames)
    trimmed = trim(frames)
    after = sum(f.get("repeat", 1) for f in trimmed)

    print(f"{path.name}: {len(frames)}→{len(trimmed)} entries, {before}→{after} real frames")

    if dry_run or trimmed == frames:
        return

    if wrapper is not None:
        wrapper["frames"] = trimmed
        out = wrapper
    else:
        out = trimmed
    path.write_text(json.dumps(out, indent=2))

if __name__ == "__main__":
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    paths = [Path(a) for a in args if not a.startswith("--")]

    if not paths:
        skills_dir = Path(__file__).parent.parent / "skills"
        paths = sorted(skills_dir.glob("*.json"))

    for p in paths:
        process(p, dry_run=dry_run)
