from terraria_agent.spinal_cord.bt import Sequence, Selector, Status
from terraria_agent.spinal_cord.conditions.health import IsHealthCritical, IsHealthLow
from terraria_agent.spinal_cord.conditions.inventory import HasPotion
from terraria_agent.spinal_cord.actions.survival import UsePotion, SignalBrainEmergency
from terraria_agent.spinal_cord.actions.combat import Dodge


def build_survival_tree():
    """hp < 20%: try potion → dodge → signal brain emergency."""
    return Sequence(
        children=[
            IsHealthCritical(threshold=0.2),
            Selector(children=[
                Sequence(children=[HasPotion(), UsePotion()]),
                Dodge(),
                SignalBrainEmergency(),
            ], name="SurvivalActions"),
        ],
        name="Survival",
    )


def build_low_health_tree():
    """hp < 50%: try potion if available."""
    return Sequence(
        children=[
            IsHealthLow(threshold=0.5),
            Selector(children=[
                Sequence(children=[HasPotion(), UsePotion()]),
            ], name="LowHealthActions"),
        ],
        name="LowHealth",
    )
