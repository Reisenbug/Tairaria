from terraria_agent.spinal_cord.bt import Sequence, Selector
from terraria_agent.spinal_cord.conditions.environment import (
    IsPitAhead, IsBlockWallAhead, IsWaterAhead, IsDark, CanJumpOverObstacle,
)
from terraria_agent.spinal_cord.conditions.inventory import HasPlatforms, HasTorch, HasPickaxe
from terraria_agent.spinal_cord.actions.movement import (
    Jump, PlacePlatform, MineForward, MoveRight, Swim,
)
from terraria_agent.spinal_cord.actions.survival import PlaceTorch


def build_terrain_tree():
    """
    TERRAIN [Selector] — handle obstacles while moving right
    ├── PIT: jump over, or bridge with platforms
    ├── BLOCK_WALL: jump if low enough, else mine through
    ├── WATER: swim through (move right + periodic jump)
    ├── DARK: place torch
    └── GO_RIGHT: default movement
    """
    return Selector(
        children=[
            Sequence(
                children=[
                    IsPitAhead(),
                    Selector(children=[
                        Sequence(children=[HasPlatforms(), PlacePlatform(), Jump()]),
                        Jump(),
                    ], name="PitStrategy"),
                ],
                name="PitHandling",
            ),
            Sequence(
                children=[
                    IsBlockWallAhead(),
                    Selector(children=[
                        Sequence(children=[CanJumpOverObstacle(), Jump()]),
                        Sequence(children=[HasPickaxe(), MineForward()]),
                        Jump(),
                    ], name="BlockWallStrategy"),
                ],
                name="BlockWallHandling",
            ),
            Sequence(
                children=[IsWaterAhead(), Swim("right")],
                name="WaterHandling",
            ),
            Sequence(
                children=[IsDark(), HasTorch(), PlaceTorch()],
                name="DarkHandling",
            ),
            MoveRight(name="GoRight"),
        ],
        name="Terrain",
    )
