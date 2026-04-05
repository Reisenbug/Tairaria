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


class Player(BaseModel):
    hp: int
    max_hp: int
    mana: int = 0
    max_mana: int = 0
    pos: tuple[float, float]
    velocity: tuple[float, float] = (0.0, 0.0)
    direction: str = "right"
    buffs: list[str] = []
    debuffs: list[str] = []


class Enemy(BaseModel):
    type: str
    pos: tuple[float, float]
    moving: str = "none"
    distance: float = 0.0
    threat: EnemyThreat = EnemyThreat.WEAK


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
    enemies: list[Enemy] = []
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
