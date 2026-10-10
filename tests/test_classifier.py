import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_heal.taxonomy import FailureTaxonomy
from agent_heal.classifier import classify, scan_metrics


def T():
    return FailureTaxonomy()


def test_sigkill_is_infra_death():
    c = classify(-9, "", [], False, False, T())
    assert c.name == "infra_death" and c.policy == "resume"


def test_exit_137_is_oom():
    c = classify(137, "", [], False, False, T())
    assert c.name == "oom" and c.policy == "shrink_retry"


def test_nan_metric_wins_over_exit_code():
    c = classify(1, "", ["metric loss=nan unit=3"], False, False, T())
    assert c.name == "nan_divergence"


def test_heartbeat_stale_is_hang():
    c = classify(None, "", [], True, False, T())
    assert c.name == "hang" and c.policy == "resume"


def test_timeout_beats_sigkill_exit():
    # our own timeout kill delivers -9; must not read as infra_death
    c = classify(-9, "", [], False, True, T())
    assert c.name == "timeout" and c.policy == "shrink_retry"


def test_stderr_signature():
    c = classify(1, "FileNotFoundError: No such file 'x.pt'", [], False,
                 False, T())
    assert c.name == "data_error" and c.policy == "retry_once"


def test_unknown_grows():
    t = T()
    c = classify(1, "SomeBizarreError: frobnicate failed", [], False, False, t)
    assert c.name.startswith("unknown:")
    assert any(e.name == c.name for e in t.entries)


def test_scan_metrics():
    assert scan_metrics(["metric loss=0.5"]) == ""
    assert scan_metrics(["metric loss=nan"]) == "nan"
    assert scan_metrics(["metric loss=inf"]) == "nan"
