from terraria_agent.spinal_cord.bt import Sequence, Selector
from terraria_agent.spinal_cord.conditions.environment import (
    IsPitAhead, IsBlockWallAhead, IsWaterAhead, IsDark, CanJumpOverObstacle,
)
from terraria_agent.spinal_cord.conditions.inventory import HasPlatforms, HasTorch, HasPickaxe
from terraria_agent.spinal_cord.actions.movement import Jump, PlacePlatform, MineForward, Swim
from terraria_agent.spinal_cord.actions.survival import PlaceTorch


def build_terrain_tree():
    """
    TERRAIN [Selector] — handle obstacles in current movement direction.
    Movement direction is decided by tasks, not here.
    Only activates when terrain_ahead != FLAT.
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
                children=[IsWaterAhead(), Swim()],
                name="WaterHandling",
            ),
            Sequence(
                children=[IsDark(), HasTorch(), PlaceTorch()],
                name="DarkHandling",
            ),
        ],
        name="Terrain",
    )
