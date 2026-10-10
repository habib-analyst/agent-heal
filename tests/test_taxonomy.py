import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_heal.taxonomy import FailureTaxonomy


def test_seed_entries_present():
    t = FailureTaxonomy()
    names = {e.name for e in t.entries}
    for n in ("infra_death", "oom", "nan_divergence", "disk_full",
              "data_error", "hang", "timeout"):
        assert n in names, n


def test_match_exit_code_sigkill():
    t = FailureTaxonomy()
    e = t.match(exit_code=-9)
    assert e is not None and e.name == "infra_death"
    assert e.policy == "resume"


def test_match_oom_stderr():
    t = FailureTaxonomy()
    e = t.match(stderr="torch.cuda.OutOfMemoryError: CUDA out of memory.")
    assert e is not None and e.name == "oom"
    assert e.policy == "shrink_retry"


def test_match_disk_full():
    t = FailureTaxonomy()
    e = t.match(stderr="OSError: [Errno 28] No space left on device")
    assert e is not None and e.name == "disk_full"


def test_match_heartbeat():
    t = FailureTaxonomy()
    e = t.match(heartbeat_stale=True)
    assert e is not None and e.name == "hang"


def test_match_metric_nan():
    t = FailureTaxonomy()
    e = t.match(metric_hit="nan")
    assert e is not None and e.name == "nan_divergence"


def test_record_and_recovery_rate(tmp_path):
    t = FailureTaxonomy(tmp_path / "tax.json")
    t.record("oom", recovered=True)
    t.record("oom", recovered=False)
    e = next(x for x in t.entries if x.name == "oom")
    assert e.times_seen == 2 and e.times_recovered == 1
    assert e.recovery_rate == 0.5
    # persistence roundtrip
    t2 = FailureTaxonomy(tmp_path / "tax.json")
    e2 = next(x for x in t2.entries if x.name == "oom")
    assert e2.times_seen == 2


def test_unknown_grows_taxonomy(tmp_path):
    t = FailureTaxonomy(tmp_path / "tax.json")
    n0 = len(t.entries)
    t.record("unknown:weird new failure", recovered=False)
    assert len(t.entries) == n0 + 1
