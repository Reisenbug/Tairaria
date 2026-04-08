from terraria_agent.spinal_cord.bt import Sequence, Selector, Parallel
from terraria_agent.spinal_cord.conditions.combat import (
    HasEnemiesNearby, IsSurrounded, EnemyIsWeak, EnemyIsMedium, EnemyIsDangerous, HasUrgentThreat,
)
from terraria_agent.spinal_cord.actions.combat import AttackNearest, SwitchToSword, SwitchToBestWeapon, Dodge
from terraria_agent.spinal_cord.actions.movement import MoveLeft


def build_threat_response_tree():
    """Urgent projectile/threat → dodge."""
    return Sequence(
        children=[HasUrgentThreat(), Dodge()],
        name="ThreatResponse",
    )


def build_combat_tree():
    """Handle enemies by threat level — weapon selection is Brain's job."""
    return Sequence(
        children=[
            HasEnemiesNearby(max_distance=400.0),
            AttackNearest(),
        ],
        name="Combat",
    )
