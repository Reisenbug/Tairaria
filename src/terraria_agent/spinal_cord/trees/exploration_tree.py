from terraria_agent.spinal_cord.bt import Sequence, Selector
from terraria_agent.spinal_cord.bt.leaves import Condition
from terraria_agent.spinal_cord.conditions.environment import (
    IsBlockWallAhead, IsWaterAhead, IsDark, CanJumpOverObstacle,
)
from terraria_agent.spinal_cord.conditions.inventory import HasTorch, HasPickaxe
from terraria_agent.spinal_cord.actions.movement import Jump, MineForward, Swim
from terraria_agent.spinal_cord.actions.survival import PlaceTorch


class NotExclusive(Condition):
    def check(self, ctx) -> bool:
        return not ctx.exclusive_active


def build_terrain_tree():
    """
    TERRAIN [Sequence] — handle obstacles in current movement direction.
    Movement direction is decided by tasks, not here.
    Defers while an EXCLUSIVE task is pinned (chop big tree, open chest, etc.).
    """
    return Sequence(
        children=[
            NotExclusive(name="NotExclusive"),
            Selector(children=[
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
            ], name="TerrainBranches"),
        ],
        name="Terrain",
    )
