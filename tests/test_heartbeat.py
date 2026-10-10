import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_heal.heartbeat import HeartbeatWriter, HeartbeatMonitor


def test_beat_not_stale(tmp_path):
    hb = tmp_path / "hb"
    w = HeartbeatWriter(hb)
    w.beat()
    m = HeartbeatMonitor(hb, timeout_s=5.0)
    assert not m.is_stale()


def test_stale_after_timeout(tmp_path):
    hb = tmp_path / "hb"
    w = HeartbeatWriter(hb)
    w.beat()
    m = HeartbeatMonitor(hb, timeout_s=0.05)
    time.sleep(0.1)
    assert m.is_stale()


def test_missing_file_is_stale(tmp_path):
    m = HeartbeatMonitor(tmp_path / "never", timeout_s=5.0)
    assert m.is_stale()
