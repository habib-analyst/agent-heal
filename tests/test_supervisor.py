"""End-to-end supervisor tests on the synthetic fault-injection job."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_heal import Supervisor

HERE = os.path.dirname(os.path.abspath(__file__))
JOB = [sys.executable, os.path.join(HERE, "..", "bench", "synthetic_job.py"),
       "--units", "4", "--unit-cost", "0.05", "--batch", "64"]


def _sup(tmp_path, **kw):
    kw.setdefault("hang_timeout_s", 2.0)
    kw.setdefault("backoff_base", 0.05)
    kw.setdefault("attempt_timeout_s", 60.0)
    return Supervisor(incident_log=str(tmp_path / "incidents.jsonl"), **kw)


def _completed_units(run_dir):
    p = os.path.join(run_dir, "progress.jsonl")
    return {json.loads(ln)["unit_id"] for ln in open(p) if ln.strip()}


def test_clean_run_recovers(tmp_path):
    s = _sup(tmp_path)
    r = s.run(JOB, "t-clean", tmp_path / "run")
    assert r.recovered and r.attempts == 1
    assert _completed_units(tmp_path / "run") == {f"unit-{i}" for i in range(4)}


def test_kill9_resumes(tmp_path):
    s = _sup(tmp_path)
    cmd = JOB + ["--fault", "kill9", "--fault-at", "2"]
    r = s.run(cmd, "t-kill9", tmp_path / "run")
    assert r.recovered, r.final_failure
    assert _completed_units(tmp_path / "run") == {f"unit-{i}" for i in range(4)}
    kinds = [i.failure for i in r.incidents]
    assert "infra_death" in kinds


def test_oom_shrinks_and_recovers(tmp_path):
    s = _sup(tmp_path)
    cmd = JOB + ["--fault", "oom", "--mem-limit", "32"]
    r = s.run(cmd, "t-oom", tmp_path / "run")
    assert r.recovered, r.final_failure
    kinds = [i.failure for i in r.incidents]
    assert "oom" in kinds


def test_nan_resumes_from_good_checkpoint(tmp_path):
    s = _sup(tmp_path)
    cmd = JOB + ["--fault", "nan", "--fault-at", "2"]
    r = s.run(cmd, "t-nan", tmp_path / "run")
    assert r.recovered, r.final_failure
    assert any(i.failure == "nan_divergence" for i in r.incidents)


def test_diskfull_cleanup_then_resume(tmp_path):
    s = _sup(tmp_path)
    cmd = JOB + ["--fault", "diskfull", "--fault-at", "1"]
    r = s.run(cmd, "t-disk", tmp_path / "run")
    assert r.recovered, r.final_failure
    assert any(i.failure == "disk_full" for i in r.incidents)


def test_hang_detected_and_resumed(tmp_path):
    s = _sup(tmp_path, hang_timeout_s=1.0)
    cmd = JOB + ["--fault", "hang", "--fault-at", "1"]
    r = s.run(cmd, "t-hang", tmp_path / "run")
    assert r.recovered, r.final_failure
    assert any(i.failure == "hang" for i in r.incidents)


def test_incident_log_written(tmp_path):
    s = _sup(tmp_path)
    cmd = JOB + ["--fault", "kill9", "--fault-at", "1"]
    s.run(cmd, "t-log", tmp_path / "run")
    rows = [json.loads(ln) for ln in
            open(tmp_path / "incidents.jsonl") if ln.strip()]
    assert len(rows) >= 2
    assert all("failure" in r and "policy" in r for r in rows)
