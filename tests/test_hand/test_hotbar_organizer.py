from terraria_agent.models.game_state import InventorySlot
from terraria_agent.hand.hotbar_organizer import plan_hotbar_swaps, HOTBAR_LAYOUT


def _slot(index, name="", damage=0, pick=0, axe=0, hammer=0, create_tile=-1, stack=1, consumable=False):
    return InventorySlot(
        slot_index=index, id=1 if name else 0, name=name, stack=stack,
        damage=damage, pick=pick, axe=axe, hammer=hammer,
        create_tile=create_tile, consumable=consumable,
    )


def _empty(index):
    return InventorySlot(slot_index=index)


def _make_slots(overrides: dict[int, InventorySlot]) -> list[InventorySlot]:
    slots = [_empty(i) for i in range(58)]
    for idx, s in overrides.items():
        slots[idx] = s
    return slots


def test_already_organized():
    slots = _make_slots({
        0: _slot(0, "Gold Broadsword", damage=20),
        1: _slot(1, "Gold Pickaxe", pick=55),
    })
    swaps = plan_hotbar_swaps(slots)
    assert swaps == []


def test_swap_weapon_from_inventory():
    slots = _make_slots({
        15: _slot(15, "Gold Broadsword", damage=20),
    })
    swaps = plan_hotbar_swaps(slots)
    assert (15, 0) in swaps


def test_swap_pickaxe_from_inventory():
    slots = _make_slots({
        22: _slot(22, "Nightmare Pickaxe", pick=65),
    })
    swaps = plan_hotbar_swaps(slots)
    assert (22, 1) in swaps


def test_best_weapon_selected():
    slots = _make_slots({
        10: _slot(10, "Copper Shortsword", damage=5),
        20: _slot(20, "Gold Broadsword", damage=20),
    })
    swaps = plan_hotbar_swaps(slots)
    assert (20, 0) in swaps


def test_no_matching_item_skipped():
    slots = _make_slots({
        0: _slot(0, "Torch", create_tile=4, stack=50),
    })
    swaps = plan_hotbar_swaps(slots)
    assert all(dst != 1 for _, dst in swaps)


def test_platform_to_slot_2():
    slots = _make_slots({
        30: _slot(30, "Wood Platform", create_tile=19, stack=99),
    })
    swaps = plan_hotbar_swaps(slots)
    assert (30, 2) in swaps


def test_block_to_slot_3():
    slots = _make_slots({
        25: _slot(25, "Stone Block", create_tile=1, stack=200),
    })
    swaps = plan_hotbar_swaps(slots)
    assert (25, 3) in swaps


def test_bomb_to_slot_7():
    slots = _make_slots({
        40: _slot(40, "Bomb", consumable=True, stack=30),
    })
    swaps = plan_hotbar_swaps(slots)
    assert (40, 7) in swaps


def test_rail_to_slot_9():
    slots = _make_slots({
        35: _slot(35, "Minecart Track", create_tile=314, stack=50),
    })
    swaps = plan_hotbar_swaps(slots)
    assert (35, 9) in swaps


def test_empty_inventory_no_swaps():
    slots = _make_slots({})
    swaps = plan_hotbar_swaps(slots)
    assert swaps == []


def test_pickaxe_not_treated_as_weapon():
    slots = _make_slots({
        15: _slot(15, "Gold Pickaxe", damage=6, pick=55),
    })
    swaps = plan_hotbar_swaps(slots)
    assert (15, 1) in swaps
    assert all(s != 15 or d != 0 for s, d in swaps)


def test_web_to_slot_4():
    slots = _make_slots({
        18: _slot(18, "Cobweb", stack=20),
    })
    swaps = plan_hotbar_swaps(slots)
    assert (18, 4) in swaps


def test_umbrella_to_slot_4():
    slots = _make_slots({
        18: _slot(18, "Umbrella"),
    })
    swaps = plan_hotbar_swaps(slots)
    assert (18, 4) in swaps
