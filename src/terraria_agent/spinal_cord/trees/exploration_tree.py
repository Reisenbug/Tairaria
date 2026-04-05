from terraria_agent.spinal_cord.bt import Sequence, Selector
from terraria_agent.spinal_cord.conditions.environment import IsPitAhead, IsBlockWallAhead, IsDark
from terraria_agent.spinal_cord.conditions.inventory import HasPlatforms, HasTorch, HasPickaxe
from terraria_agent.spinal_cord.actions.movement import Jump, PlacePlatform
from terraria_agent.spinal_cord.actions.survival import PlaceTorch


def build_terrain_tree():
    """Handle terrain obstacles: pit, block wall, darkness."""
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
                        Sequence(children=[HasPickaxe()]),
                        Sequence(children=[HasPlatforms(), PlacePlatform(), Jump()]),
                        Jump(),
                    ], name="BlockWallStrategy"),
                ],
                name="BlockWallHandling",
            ),
            Sequence(
                children=[IsDark(), HasTorch(), PlaceTorch()],
                name="DarkHandling",
            ),
        ],
        name="Terrain",
    )
