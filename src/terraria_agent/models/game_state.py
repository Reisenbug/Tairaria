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


class WorldObject(BaseModel):
    type: str
    pos: tuple[float, float]
    distance: float = 0.0


class GameState(BaseModel):
    player: Player
    camera: Camera = Camera()
    enemies: list[Enemy] = []
    town_npcs: list[TownNpc] = []
    threats: list[Threat] = []
    objects: list[WorldObject] = []
    terrain_ahead: TerrainType = TerrainType.FLAT
    terrain_behind: TerrainType = TerrainType.FLAT
    equipped: str = "none"
    hotbar: list[Optional[str]] = [None] * 10
    inventory: dict[str, int] = {}
    is_dark: bool = False
    time_of_day: str = "day"
    biome: str = "forest"
