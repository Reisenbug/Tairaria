from terraria_agent.spinal_cord.bt import PrioritySelector, Sequence
from terraria_agent.spinal_cord.conditions.combat import (
    HasUrgentThreat, IsEnemyBlockingPath, ShouldEngage,
)
from terraria_agent.spinal_cord.actions.combat import (
    AttackNearest, Dodge, EnsureWeaponSlot, JumpOverEnemy,
)


def build_threat_response_tree():
    return Sequence(
        children=[HasUrgentThreat(), Dodge()],
        name="ThreatResponse",
    )


def build_combat_tree():
    engage = Sequence(
        children=[
            ShouldEngage(max_distance=25.0),
            EnsureWeaponSlot(),
            AttackNearest(),
        ],
        name="Engage",
    )
    avoid = Sequence(
        children=[
            IsEnemyBlockingPath(max_distance=4.0),
            JumpOverEnemy(),
        ],
        name="AvoidWeak",
    )
    return PrioritySelector(
        children=[engage, avoid],
        name="Combat",
    )
