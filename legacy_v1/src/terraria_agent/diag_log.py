from __future__ import annotations

import pathlib
import time

_DIR = pathlib.Path("logs")
_MAX_BYTES = 2_000_000
_MAX_FILES = 5
_files: dict[str, object] = {}


def _rotate(channel: str) -> None:
    base = _DIR / f"{channel}.log"
    for i in range(_MAX_FILES - 1, 0, -1):
        src = base if i == 1 else _DIR / f"{channel}.log.{i - 1}"
        dst = _DIR / f"{channel}.log.{i}"
        if src.exists():
            if dst.exists():
                dst.unlink()
            src.rename(dst)


def diag(channel: str, msg: str) -> None:
    _DIR.mkdir(exist_ok=True)
    f = _files.get(channel)
    path = _DIR / f"{channel}.log"
    if f is not None and path.exists() and path.stat().st_size > _MAX_BYTES:
        f.close()
        _rotate(channel)
        f = None
    if f is None:
        f = open(path, "a", buffering=1)
        _files[channel] = f
    f.write(f"{time.time():.3f} {msg}\n")
