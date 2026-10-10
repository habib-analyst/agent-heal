"""Fault-injection benchmark: agent-heal vs naive fixed retry.

Matrix: faults {kill9, nan, diskfull, hang, oom} x strategies {heal, naive}
x REPEATS. Each cell runs bench/synthetic_job.py and measures:
  recovered   — did the job finish all units?
  cpu_s       — total child CPU seconds across attempts (RUSAGE_CHILDREN)
  wall_s      — total wall seconds
  attempts    — attempts used

Naive baseline (what most people actually do): rerun the whole job from
scratch, up to 3 attempts, fixed 0.5s backoff, no classification, no resume.
Deterministic faults (oom) can never be recovered this way.

Results are per-cell JSONL (fsync'd); completed cells are skipped on
relaunch (the benchmark dogfoods the resume pattern).
"""

import argparse
import json
import os
import resource
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from agent_heal import Supervisor  # noqa: E402

JOB = [sys.executable, os.path.join(HERE, "synthetic_job.py"),
       "--units", "8", "--unit-cost", "0.3", "--batch", "64"]

FAULTS = {
    "kill9":    ["--fault", "kill9", "--fault-at", "3"],
    "nan":      ["--fault", "nan", "--fault-at", "3"],
    "diskfull": ["--fault", "diskfull", "--fault-at", "3"],
    "hang":     ["--fault", "hang", "--fault-at", "3"],
    "oom":      ["--fault", "oom", "--mem-limit", "32"],
}

REPEATS = 3


def _child_cpu():
    ru = resource.getrusage(resource.RUSAGE_CHILDREN)
    return ru.ru_utime + ru.ru_stime


def run_naive(cmd, workdir):
    """Rerun-from-scratch, 3 attempts, fixed backoff. Returns dict."""
    total_cpu, t0, attempts = 0.0, time.monotonic(), 0
    for attempt in range(3):
        d = os.path.join(workdir, f"naive_attempt{attempt}")
        os.makedirs(d, exist_ok=True)
        env = dict(os.environ, AGENT_HEAL_ATTEMPT=str(attempt),
                   AGENT_HEAL_SHRINK="1.0",
                   AGENT_HEAL_PROGRESS=os.path.join(d, "progress.jsonl"),
                   AGENT_HEAL_HEARTBEAT=os.path.join(d, "hb"))
        # fresh progress file per attempt == no resume (true naive retry)
        if os.path.exists(env["AGENT_HEAL_PROGRESS"]):
            os.remove(env["AGENT_HEAL_PROGRESS"])
        out = os.path.join(d, "stdout.log")
        cpu0, w0 = _child_cpu(), time.monotonic()
        try:
            with open(out, "w") as f:
                # timeout bounds the hang fault (a wedged naive job would
                # otherwise block forever); TimeoutExpired => failed attempt
                rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT,
                                    env=env, cwd=d, timeout=25).returncode
        except subprocess.TimeoutExpired:
            rc = -99
            with open(out, "a") as f:
                f.write("\n[naive] attempt timed out (hang)\n")
        total_cpu += _child_cpu() - cpu0
        attempts += 1
        wall = time.monotonic() - w0
        txt = open(out, errors="replace").read()
        if rc == 0 and "JOB DONE" in txt:
            return {"recovered": True, "cpu_s": round(total_cpu, 3),
                    "wall_s": round(time.monotonic() - t0, 3),
                    "attempts": attempts}
        time.sleep(0.5)
    return {"recovered": False, "cpu_s": round(total_cpu, 3),
            "wall_s": round(time.monotonic() - t0, 3), "attempts": attempts}


def run_heal(cmd, workdir, fault):
    d = os.path.join(workdir, "heal")
    os.makedirs(d, exist_ok=True)
    sup = Supervisor(
        incident_log=os.path.join(d, "incidents.jsonl"),
        max_attempts=5, hang_timeout_s=3.0, attempt_timeout_s=120.0,
        backoff_base=0.2, poll_s=0.2)
    r = sup.run(cmd, job_id=f"bench-{fault}", run_dir=d)
    return {"recovered": r.recovered, "cpu_s": r.total_cpu_s,
            "wall_s": r.total_wall_s, "attempts": r.attempts,
            "final_failure": r.final_failure}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=os.path.join(HERE, "..", "results"))
    p.add_argument("--faults", default=",".join(FAULTS))
    a = p.parse_args()
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    cells_f = os.path.join(out, "cells.jsonl")

    done = set()
    if os.path.exists(cells_f):
        for ln in open(cells_f):
            try:
                r = json.loads(ln)
                done.add((r["fault"], r["strategy"], r["rep"]))
            except (json.JSONDecodeError, KeyError):
                pass

    def save(rec):
        with open(cells_f, "a") as f:
            f.write(json.dumps(rec) + "\n")
            f.flush()
            os.fsync(f.fileno())

    for fault in a.faults.split(","):
        for strategy in ("heal", "naive"):
            for rep in range(REPEATS):
                key = (fault, strategy, rep)
                if key in done:
                    print(f"skip {fault}/{strategy}/{rep} (done)", flush=True)
                    continue
                cmd = JOB + FAULTS[fault]
                workdir = tempfile.mkdtemp(prefix=f"healbench_{fault}_")
                t0 = time.monotonic()
                if strategy == "heal":
                    res = run_heal(cmd, workdir, fault)
                else:
                    res = run_naive(cmd, workdir)
                rec = {"fault": fault, "strategy": strategy, "rep": rep,
                       **res, "cell_wall_s": round(time.monotonic() - t0, 1)}
                save(rec)
                print(f"done {fault}/{strategy}/{rep}: recovered="
                      f"{res['recovered']} cpu={res['cpu_s']}s "
                      f"wall={res['wall_s']}s attempts={res['attempts']}",
                      flush=True)

    # summary
    cells = [json.loads(ln) for ln in open(cells_f) if ln.strip()]
    summary = {}
    for fault in FAULTS:
        for strategy in ("heal", "naive"):
            rows = [c for c in cells if c["fault"] == fault
                    and c["strategy"] == strategy]
            if not rows:
                continue
            rec = [r for r in rows if r["recovered"]]
            summary[f"{fault}/{strategy}"] = {
                "n": len(rows),
                "recovery_rate": round(sum(r["recovered"] for r in rows)
                                      / len(rows), 3),
                "mean_cpu_s": round(sum(r["cpu_s"] for r in rec) / len(rec), 3)
                if rec else None,
                "mean_wall_s": round(sum(r["wall_s"] for r in rec) / len(rec), 3)
                if rec else None,
                "mean_attempts": round(sum(r["attempts"] for r in rows)
                                       / len(rows), 2),
            }
    with open(os.path.join(out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print("\n=== SUMMARY ===")
    for k, v in summary.items():
        print(f"{k:14s} rec={v['recovery_rate']} "
              f"cpu={v['mean_cpu_s']}s wall={v['mean_wall_s']}s "
              f"att={v['mean_attempts']} (n={v['n']})")


if __name__ == "__main__":
    main()
