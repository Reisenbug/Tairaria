"""Async client for TerraBlind mod navigation.

Single navigation in flight at a time. `start()` fires the request and returns
immediately; `poll()` is called every tick to advance state. `stop()` cancels.

Auto-fallback: goals beyond 60 tiles (manhattan) go via segmented nav.

Failure cache: a goal that has failed >=3 times in 60s on the same 4-tile bucket
is short-circuited; `start()` returns a synthetic ("failed", "repeat_fail", ...)
without bothering the mod.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Literal, Optional


_BASE = "http://127.0.0.1:17878"
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_TIMEOUT = 2.0

NAV_MAX_DIST = 60      # mirrors mod's NavCoordinator.NavMaxDist
_CACHE_TTL = 60.0
_CACHE_THRESHOLD = 3
_CACHE_BUCKET = 4      # tiles; goals quantized to this grid share a cache slot
_POLL_MIN_INTERVAL = 0.1  # don't hammer /nav_done

Status = Literal["idle", "running", "done", "failed"]


@dataclass
class NavResult:
    status: Status                    # "running" | "done" | "failed"
    reason: str = ""                  # "done" | code from mod | "repeat_fail" | "http_error"
    ctx: dict | None = None
    goal: tuple[int, int] | None = None
    elapsed_sec: float = 0.0
    human: str = ""                   # one-line summary for prompts/logs


_REASON_HUMAN = {
    "done":             "到达目标",
    "too_far":          "目标太远",                   # should be invisible (auto fallback)
    "unreachable":      "目标无法到达（地形阻挡或目标无效）",
    "replan_storm":     "反复规划失败（地形 corner case），建议换目标",
    "no_resource":      "缺少必需物品",
    "cancelled":        "导航被打断",
    "no_player":        "玩家状态异常",
    "timeout":          "超时未到达",
    "too_many_skips":   "分段导航跳过太多 waypoint",
    "bad_request":      "请求参数错误",
    "repeat_fail":      "同一目标短时间内反复失败，已熔断",
    "http_error":       "无法连接 mod",
}


def _humanize(code: str, ctx: dict | None) -> str:
    base = _REASON_HUMAN.get(code, code)
    if ctx and code == "no_resource":
        kind = ctx.get("kind")
        if kind:
            return f"{base}（{kind}）"
    return base


def _http(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(_BASE + path, data=data, headers=headers, method=method)
    try:
        with _OPENER.open(req, timeout=_TIMEOUT) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"ok": False, "reason": f"http_{e.code}"}
    except Exception as e:
        return {"ok": False, "reason": "http_error", "msg": str(e)}


def _bucket(goal: tuple[int, int]) -> tuple[int, int]:
    return (goal[0] // _CACHE_BUCKET, goal[1] // _CACHE_BUCKET)


class NavClient:
    def __init__(self) -> None:
        self._goal: Optional[tuple[int, int]] = None
        self._mode: Literal["", "nav", "seg"] = ""
        self._started_at: float = 0.0
        self._last_poll: float = 0.0
        self._last_result: Optional[NavResult] = None
        # bucket → list[(timestamp, reason)]
        self._failures: dict[tuple[int, int], list[tuple[float, str]]] = {}

    # ---- public ----

    def is_running(self) -> bool:
        return self._goal is not None

    def current_goal(self) -> Optional[tuple[int, int]]:
        return self._goal

    def last_result(self) -> Optional[NavResult]:
        return self._last_result

    def start(self, gx: int, gy: int, player_tile: tuple[int, int] | None = None) -> NavResult:
        """Start nav to (gx, gy). Returns initial NavResult.

        player_tile: optional (pcx, pcy) for client-side distance check; if omitted,
        we let mod do the check. Used only to choose nav vs seg.
        """
        if self.is_running():
            self.stop()

        goal = (gx, gy)
        # circuit breaker
        bucket = _bucket(goal)
        now = time.time()
        recent = [(t, r) for (t, r) in self._failures.get(bucket, []) if now - t < _CACHE_TTL]
        self._failures[bucket] = recent
        if len(recent) >= _CACHE_THRESHOLD:
            res = NavResult(status="failed", reason="repeat_fail",
                            ctx={"count": len(recent), "recent_reasons": [r for _, r in recent[-3:]]},
                            goal=goal, human=_humanize("repeat_fail", None))
            self._last_result = res
            return res

        # decide endpoint
        use_seg = False
        if player_tile is not None:
            dist = abs(gx - player_tile[0]) + abs(gy - player_tile[1])
            use_seg = dist > NAV_MAX_DIST

        if use_seg:
            r = _http("POST", "/start_seg_nav", {"gx": gx, "gy": gy})
            mode = "seg"
        else:
            r = _http("POST", "/nav", {"gx": gx, "gy": gy})
            mode = "nav"
            # bounded /nav rejects with too_far if we mis-estimated distance — fallback
            if not r.get("ok") and r.get("reason") == "too_far":
                r = _http("POST", "/start_seg_nav", {"gx": gx, "gy": gy})
                mode = "seg"

        if not r.get("ok"):
            code = r.get("reason", "unknown")
            ctx = {k: v for k, v in r.items() if k not in ("ok", "reason")}
            res = NavResult(status="failed", reason=code, ctx=ctx, goal=goal,
                            human=_humanize(code, ctx))
            self._record_failure(bucket, code)
            self._last_result = res
            return res

        self._goal = goal
        self._mode = mode
        self._started_at = now
        self._last_poll = 0.0
        res = NavResult(status="running", goal=goal,
                        human=f"导航中: ({gx},{gy}) via {mode}")
        self._last_result = res
        return res

    def poll(self) -> NavResult:
        """Call every tick. Returns current state; transitions to done/failed once."""
        if self._goal is None:
            return self._last_result or NavResult(status="idle", reason="idle")

        now = time.time()
        if now - self._last_poll < _POLL_MIN_INTERVAL:
            return NavResult(status="running", goal=self._goal,
                             elapsed_sec=now - self._started_at)
        self._last_poll = now

        ep = "/seg_nav_done" if self._mode == "seg" else "/nav_done"
        r = _http("GET", ep)
        status_str = r.get("status", "")
        if status_str == "running":
            return NavResult(status="running", goal=self._goal,
                             elapsed_sec=now - self._started_at)

        # terminal
        goal = self._goal
        elapsed = now - self._started_at
        if r.get("done"):
            res = NavResult(status="done", reason="done", goal=goal,
                            elapsed_sec=elapsed, human=_humanize("done", None))
            self._goal = None
            self._mode = ""
            self._last_result = res
            return res
        # failed (or idle from seg if never started — treat as failed)
        code = r.get("reason", "unknown")
        ctx = {k: v for k, v in r.items() if k not in ("done", "status", "reason", "legacy_reason")}
        res = NavResult(status="failed", reason=code, ctx=ctx, goal=goal,
                        elapsed_sec=elapsed, human=_humanize(code, ctx))
        self._record_failure(_bucket(goal), code)
        self._goal = None
        self._mode = ""
        self._last_result = res
        return res

    def stop(self) -> None:
        """Cancel current navigation. Safe to call when idle."""
        if self._goal is None:
            return
        ep = "/stop_seg_nav" if self._mode == "seg" else "/nav_stop"
        _http("POST", ep, {})
        self._goal = None
        self._mode = ""

    # ---- internal ----

    def _record_failure(self, bucket: tuple[int, int], reason: str) -> None:
        if reason in ("cancelled", "done"):
            return  # don't count self-cancellation toward circuit breaker
        self._failures.setdefault(bucket, []).append((time.time(), reason))
