from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from typing import Callable

from terraria_agent.models.game_state import InventorySlot


_SWAP_URL = "http://127.0.0.1:17878/swap"
_NO_PROXY_HANDLER = urllib.request.ProxyHandler({})
_OPENER = urllib.request.build_opener(_NO_PROXY_HANDLER)


@dataclass
class SlotRule:
    slot: int
    match: Callable[[InventorySlot], bool]
    priority: Callable[[InventorySlot], float]


def _is_rail(s: InventorySlot) -> bool:
    low = s.name.lower()
    return "rail" in low or "minecart" in low or "track" in low


HOTBAR_LAYOUT: list[SlotRule] = [
    SlotRule(0, match=lambda s: s.is_weapon, priority=lambda s: s.damage),
    SlotRule(1, match=lambda s: s.is_pickaxe, priority=lambda s: s.pick),
    SlotRule(2, match=lambda s: s.is_platform, priority=lambda s: s.stack),
    SlotRule(3, match=lambda s: s.is_block and not _is_rail(s), priority=lambda s: s.stack),
    SlotRule(4, match=lambda s: "web" in s.name.lower() or "umbrella" in s.name.lower(), priority=lambda s: 1.0),
    SlotRule(7, match=lambda s: "bomb" in s.name.lower() or "dynamite" in s.name.lower(), priority=lambda s: s.stack),
    SlotRule(9, match=_is_rail, priority=lambda s: s.stack),
]


def plan_hotbar_swaps(
    inventory_slots: list[InventorySlot],
    layout: list[SlotRule] | None = None,
) -> list[tuple[int, int]]:
    layout = layout or HOTBAR_LAYOUT
    claimed: set[int] = set()
    swaps: list[tuple[int, int]] = []

    for rule in layout:
        current = next((s for s in inventory_slots if s.slot_index == rule.slot), None)
        if current and not current.is_empty and rule.match(current):
            claimed.add(rule.slot)
            continue

        candidates = [
            s for s in inventory_slots
            if not s.is_empty and rule.match(s) and s.slot_index not in claimed
        ]
        if not candidates:
            continue

        best = max(candidates, key=rule.priority)
        if best.slot_index == rule.slot:
            claimed.add(rule.slot)
            continue

        swaps.append((best.slot_index, rule.slot))
        claimed.add(rule.slot)
        claimed.add(best.slot_index)

    return swaps


def swap_slot(src: int, dst: int) -> bool:
    try:
        url = f"{_SWAP_URL}?src={src}&dst={dst}"
        with _OPENER.open(url, timeout=0.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def organize_hotbar(inventory_slots: list[InventorySlot], layout: list[SlotRule] | None = None) -> list[tuple[int, int]]:
    swaps = plan_hotbar_swaps(inventory_slots, layout)
    for src, dst in swaps:
        swap_slot(src, dst)
    return swaps
