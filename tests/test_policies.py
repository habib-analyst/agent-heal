import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_heal.policies import decide, backoff


def test_backoff_bounds():
    for a in range(6):
        d = backoff(a, base=2.0, cap=60.0)
        assert 0 < d <= 60.0 * 1.25


def test_resume_escalates_at_budget():
    d = decide("resume", {}, attempt=5, max_attempts=5)
    assert d.escalate
    d = decide("resume", {}, attempt=0, max_attempts=5)
    assert not d.escalate and d.policy == "resume"


def test_shrink_compounds():
    # shrink_factor returned is for the NEXT attempt: 0.5, 0.25, 0.125
    d0 = decide("shrink_retry", {"shrink_factor": 0.5}, attempt=0)
    d1 = decide("shrink_retry", {"shrink_factor": 0.5}, attempt=1)
    d2 = decide("shrink_retry", {"shrink_factor": 0.5}, attempt=2)
    assert (d0.shrink_factor, d1.shrink_factor, d2.shrink_factor) == (0.5, 0.25, 0.125)


def test_retry_once_then_escalate():
    d = decide("retry_once", {"max_retries": 1}, attempt=0)
    assert not d.escalate
    d = decide("retry_once", {"max_retries": 1}, attempt=1)
    assert d.escalate


def test_escalate_policy():
    d = decide("escalate", {}, attempt=0)
    assert d.escalate
