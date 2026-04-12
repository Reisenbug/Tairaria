from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class EnemyThreat(str, Enum):
    WEAK = "weak"
    MEDIUM = "medium"
    DANGEROUS = "dangerous"
    BOSS = "boss"


class TerrainType(str, Enum):
    FLAT = "flat"
    PIT = "pit"
    BLOCK_WALL = "block_wall"
    PLATFORM = "platform"
    WATER = "water"
    LAVA = "lava"


class InventorySlot(BaseModel):
    slot_index: int
    id: int = 0
    name: str = ""
    stack: int = 0
    damage: int = 0
    pick: int = 0
    axe: int = 0
    hammer: int = 0
    create_tile: int = -1
    consumable: bool = False

    @property
    def is_empty(self) -> bool:
        return self.id == 0

    @property
    def is_weapon(self) -> bool:
        return self.damage > 0 and self.pick == 0 and self.axe == 0 and self.hammer == 0

    @property
    def is_pickaxe(self) -> bool:
        return self.pick > 0

    @property
    def is_axe(self) -> bool:
        return self.axe > 0

    @property
    def is_platform(self) -> bool:
        return "platform" in self.name.lower()

    @property
    def is_block(self) -> bool:
        return self.create_tile >= 0 and not self.is_platform


class Camera(BaseModel):
    screen_pos: tuple[float, float] = (0.0, 0.0)
    screen_size: tuple[int, int] = (0, 0)
    zoom: float = 1.0


class Player(BaseModel):
    hp: int
    max_hp: int
    mana: int = 0
    max_mana: int = 0
    pos: tuple[float, float]
    width: float = 0.0
    height: float = 0.0
    velocity: tuple[float, float] = (0.0, 0.0)
    direction: str = "right"
    buffs: list[str] = []
    debuffs: list[str] = []
    took_damage: bool = False
    damage_amount: int = 0
    danger_level: str = "safe"
    hp_trend: str = "stable"
    selected_slot: int = 0
    inventory_open: bool = False


class Enemy(BaseModel):
    who: int = -1
    type_id: int = 0
    type: str
    pos: tuple[float, float]
    velocity: tuple[float, float] = (0.0, 0.0)
    width: float = 0.0
    height: float = 0.0
    hp: int = 0
    max_hp: int = 1
    boss: bool = False
    distance: float = 0.0
    threat: EnemyThreat = EnemyThreat.WEAK


class TownNpc(BaseModel):
    who: int = -1
    type_id: int = 0
    name: str = ""
    display_name: str = ""
    pos: tuple[float, float] = (0.0, 0.0)
    homeless: bool = False


class Threat(BaseModel):
    type: str
    pos: tuple[float, float]
    direction: str = "none"
    urgent: bool = False


class TileRun(BaseModel):
    type: int
    sflags: int
    count: int

    @property
    def active(self) -> bool:
        return bool(self.sflags & 1)

    @property
    def solid(self) -> bool:
        return bool(self.sflags & 2)

    @property
    def water(self) -> bool:
        return bool(self.sflags & 4)

    @property
    def lava(self) -> bool:
        return bool(self.sflags & 8)

    @property
    def honey(self) -> bool:
        return bool(self.sflags & 16)

    @property
    def shimmer(self) -> bool:
        return bool(self.sflags & 32)


class TileWindow(BaseModel):
    origin: tuple[int, int] = (0, 0)
    width: int = 120
    height: int = 80
    rows: list[list[TileRun]] = []

    def tile_at(self, world_x: int, world_y: int) -> Optional[TileRun]:
        ry = world_y - self.origin[1]
        rx = world_x - self.origin[0]
        if ry < 0 or ry >= self.height or rx < 0 or rx >= self.width:
            return None
        col = 0
        for run in self.rows[ry]:
            if rx < col + run.count:
                return run
            col += run.count
        return None


class DroppedItem(BaseModel):
    who: int = -1
    type_id: int = 0
    name: str = ""
    stack: int = 0
    pos: tuple[float, float] = (0.0, 0.0)
    distance: float = 0.0


class WorldObject(BaseModel):
    type: str
    pos: tuple[float, float]
    tile_pos: tuple[int, int] = (0, 0)
    distance: float = 0.0


class GameState(BaseModel):
    player: Player
    camera: Camera = Camera()
    enemies: list[Enemy] = []
    town_npcs: list[TownNpc] = []
    threats: list[Threat] = []
    tile_window: Optional[TileWindow] = None
    objects: list[WorldObject] = []
    dropped_items: list[DroppedItem] = []
    terrain_ahead: TerrainType = TerrainType.FLAT
    terrain_behind: TerrainType = TerrainType.FLAT
    equipped: str = "none"
    hotbar: list[Optional[str]] = [None] * 10
    inventory: dict[str, int] = {}
    inventory_slots: list[InventorySlot] = []
    smart_cursor: bool = False
    is_dark: bool = False
    time_of_day: str = "day"
    biome: str = "forest"
