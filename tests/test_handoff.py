import pytest
from features.handoff import detect_handoff_in_response, HandoffRequest


def test_detect_handoff_present():
    response = "I've finished the refactor.\n@Bob@host2: Here is the handoff.\n- Files changed: a.py\n- Next: fix tests"
    result = detect_handoff_in_response(response)
    assert result is not None
    assert isinstance(result, HandoffRequest)
    assert result.target_agent == "bob"
    assert result.target_host == "host2"
    assert "handoff" in result.content.lower()


def test_detect_handoff_absent():
    response = "I've finished the refactor. All tests pass."
    result = detect_handoff_in_response(response)
    assert result is None


def test_detect_handoff_hyphenated_host():
    response = "@Dana@dev-box: Take over the deployment."
    result = detect_handoff_in_response(response)
    assert result is not None
    assert result.target_host == "dev-box"


def test_detect_handoff_multiline_content():
    response = "@Alex@host3: Handoff.\n- Item 1\n- Item 2\n- Item 3"
    result = detect_handoff_in_response(response)
    assert result is not None
    assert "Item 1" in result.content
