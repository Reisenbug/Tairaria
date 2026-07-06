from __future__ import annotations

import pytest

from terraria_agent.spinal_cord.bt.composites import (
    DynamicSelector,
    Parallel,
    PrioritySelector,
    Selector,
    Sequence,
)
from terraria_agent.spinal_cord.bt.core import Node, Status


class Fixed(Node):
    def __init__(self, status: Status, name: str):
        super().__init__(name)
        self._status = status

    def tick(self, ctx) -> Status:
        return self._status


class TestBTTrace:
    def test_sequence_running_appends_trace(self, default_state, make_ctx):
        ctx = make_ctx(default_state)
        tree = Sequence([Fixed(Status.SUCCESS, "A"), Fixed(Status.RUNNING, "B")], name="Seq")
        tree.tick(ctx)
        assert "Seq>B" in ctx.bt_trace

    def test_sequence_success_no_trace(self, default_state, make_ctx):
        ctx = make_ctx(default_state)
        tree = Sequence([Fixed(Status.SUCCESS, "A"), Fixed(Status.SUCCESS, "B")], name="Seq")
        status = tree.tick(ctx)
        assert status == Status.SUCCESS
        assert ctx.bt_trace == []

    def test_selector_success_appends_trace(self, default_state, make_ctx):
        ctx = make_ctx(default_state)
        tree = Selector([Fixed(Status.FAILURE, "A"), Fixed(Status.SUCCESS, "B")], name="Sel")
        tree.tick(ctx)
        assert "Sel>B" in ctx.bt_trace

    def test_selector_running_appends_trace(self, default_state, make_ctx):
        ctx = make_ctx(default_state)
        tree = Selector([Fixed(Status.FAILURE, "A"), Fixed(Status.RUNNING, "B")], name="Sel")
        tree.tick(ctx)
        assert "Sel>B" in ctx.bt_trace

    def test_priority_selector_trace(self, default_state, make_ctx):
        ctx = make_ctx(default_state)
        tree = PrioritySelector(
            [Fixed(Status.FAILURE, "Hi"), Fixed(Status.RUNNING, "Mid"), Fixed(Status.SUCCESS, "Lo")],
            name="Prio",
        )
        tree.tick(ctx)
        assert "Prio>Mid" in ctx.bt_trace

    def test_nested_trace(self, default_state, make_ctx):
        ctx = make_ctx(default_state)
        inner = Sequence([Fixed(Status.SUCCESS, "X"), Fixed(Status.RUNNING, "Y")], name="Inner")
        outer = PrioritySelector([Fixed(Status.FAILURE, "A"), inner], name="Outer")
        outer.tick(ctx)
        assert "Inner>Y" in ctx.bt_trace
        assert "Outer>Inner" in ctx.bt_trace

    def test_parallel_running_appends_trace(self, default_state, make_ctx):
        ctx = make_ctx(default_state)
        tree = Parallel(
            [Fixed(Status.RUNNING, "A"), Fixed(Status.SUCCESS, "B")],
            success_threshold=2,
            name="Par",
        )
        tree.tick(ctx)
        assert "Par>A" in ctx.bt_trace

    def test_dynamic_selector_trace(self, default_state, make_ctx):
        ctx = make_ctx(default_state)
        tree = DynamicSelector(
            provider=lambda c: [Fixed(Status.FAILURE, "A"), Fixed(Status.RUNNING, "B")],
            name="Dyn",
        )
        tree.tick(ctx)
        assert "Dyn>B" in ctx.bt_trace

    def test_trace_is_fresh_per_context(self, default_state, make_ctx):
        ctx1 = make_ctx(default_state)
        ctx2 = make_ctx(default_state)
        tree = Sequence([Fixed(Status.RUNNING, "B")], name="Seq")
        tree.tick(ctx1)
        assert ctx2.bt_trace == []
