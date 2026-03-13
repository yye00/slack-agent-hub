import pytest
from core.heartbeat import HeartbeatState, TipRotator


def test_heartbeat_state_records_tool():
    state = HeartbeatState()
    state.record_tool("Read", "lib/parser.py")
    assert state.tool_count == 1
    assert state.last_tool == "Read lib/parser.py"
    assert len(state.recent_tools) == 1


def test_heartbeat_state_ring_buffer():
    state = HeartbeatState()
    for i in range(7):
        state.record_tool(f"Tool{i}", f"arg{i}")
    assert len(state.recent_tools) == 5  # Ring buffer of 5
    assert state.recent_tools[0] == "Tool2(arg2)"


def test_heartbeat_state_tool_counts():
    state = HeartbeatState()
    state.record_tool("Read", "a.py")
    state.record_tool("Read", "b.py")
    state.record_tool("Edit", "a.py")
    state.record_tool("Bash", "pytest")
    counts = state.tool_counts_by_category()
    assert counts["Read"] == 2
    assert counts["Edit"] == 1
    assert counts["Bash"] == 1


def test_heartbeat_state_stall_detection():
    state = HeartbeatState()
    assert state.is_stalled(threshold_secs=300) is False
    # Simulate no activity — last_tool_time stays at None
    # With no tools recorded, not considered stalled (just started)


def test_tip_rotator_cycles():
    tips = ["tip1", "tip2", "tip3"]
    rotator = TipRotator(tips)
    seen = set()
    for _ in range(3):
        tip = rotator.next()
        assert tip not in seen
        seen.add(tip)
    assert seen == {"tip1", "tip2", "tip3"}


def test_tip_rotator_wraps():
    rotator = TipRotator(["a", "b"])
    rotator.next()
    rotator.next()
    # Should wrap around
    tip = rotator.next()
    assert tip in ("a", "b")


def test_tip_rotator_disabled():
    rotator = TipRotator([], enabled=False)
    assert rotator.next() is None
