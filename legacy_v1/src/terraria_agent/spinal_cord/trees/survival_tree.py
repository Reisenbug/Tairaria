from terraria_agent.spinal_cord.bt import Sequence, Selector, Status
from terraria_agent.spinal_cord.conditions.health import IsHealthCritical, IsHealthLow
from terraria_agent.spinal_cord.actions.survival import UsePotion, SignalBrainEmergency
from terraria_agent.spinal_cord.actions.combat import Dodge


def build_survival_tree():
    """hp < 20%: try potion → dodge → signal brain emergency."""
    return Sequence(
        children=[
            IsHealthCritical(threshold=0.2),
            Selector(children=[
                UsePotion(),
                Dodge(),
                SignalBrainEmergency(),
            ], name="SurvivalActions"),
        ],
        name="Survival",
    )


def build_low_health_tree():
    """hp < 50%: try quick heal."""
    return Sequence(
        children=[
            IsHealthLow(threshold=0.5),
            UsePotion(),
        ],
        name="LowHealth",
    )
