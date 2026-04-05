from terraria_agent.spinal_cord.bt.core import Status, Node
from terraria_agent.spinal_cord.context import TickContext


class SuccessNode(Node):
    def tick(self, ctx): return Status.SUCCESS

class FailureNode(Node):
    def tick(self, ctx): return Status.FAILURE

class RunningNode(Node):
    def tick(self, ctx): return Status.RUNNING


def test_status_values():
    assert Status.SUCCESS.value == "success"
    assert Status.FAILURE.value == "failure"
    assert Status.RUNNING.value == "running"


def test_node_default_name():
    node = SuccessNode()
    assert node.name == "SuccessNode"


def test_node_custom_name():
    node = SuccessNode(name="my_node")
    assert node.name == "my_node"


def test_node_repr():
    node = SuccessNode(name="test")
    assert repr(node) == "SuccessNode('test')"


def test_node_reset_is_noop():
    node = SuccessNode()
    node.reset()
