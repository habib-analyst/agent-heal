import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_heal.checkpoint import ProgressWriter, read_completed


def test_fsync_roundtrip(tmp_path):
    p = str(tmp_path / "progress.jsonl")
    w = ProgressWriter(p)
    w.log({"unit_id": "unit-0", "loss": 0.5})
    w.log({"unit_id": "unit-1", "loss": 0.4})
    assert read_completed(p) == {"unit-0", "unit-1"}


def test_error_records_not_completed(tmp_path):
    p = str(tmp_path / "progress.jsonl")
    w = ProgressWriter(p)
    w.log({"unit_id": "unit-0"})
    w.error("unit-1", RuntimeError("boom"))
    assert read_completed(p) == {"unit-0"}


def test_missing_file(tmp_path):
    assert read_completed(str(tmp_path / "nope.jsonl")) == set()


def test_corrupt_line_skipped(tmp_path):
    p = str(tmp_path / "progress.jsonl")
    with open(p, "w") as f:
        f.write('{"unit_id": "unit-0"}\nNOT JSON\n')
    assert read_completed(p) == {"unit-0"}
