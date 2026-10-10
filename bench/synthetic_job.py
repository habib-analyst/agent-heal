"""Synthetic long-running job with injectable faults (for the benchmark).

Speaks the agent-heal checkpoint-resume protocol:
  AGENT_HEAL_PROGRESS  fsync'd JSONL of completed unit_ids (skipped on resume)
  AGENT_HEAL_HEARTBEAT heartbeat file, touched per unit
  AGENT_HEAL_ATTEMPT   0-based attempt (faults fire on attempt 0, unless noted)
  AGENT_HEAL_SHRINK    shrink factor: scales batch and per-unit CPU cost
  AGENT_HEAL_DISK_FIXED  set by the supervisor's disk_full cleanup hook

Faults (all deterministic given the seed):
  kill9    SIGKILL self at unit K            -> infra_death  (transient)
  nan      NaN metric + stderr, exit 1 at K  -> nan_divergence (transient)
  diskfull OSError ENOSPC at unit K         -> disk_full    (transient*)
  hang     stop heartbeating, sleep forever  -> hang         (transient)
  oom      batch*shrink > mem_limit         -> oom          (DETERMINISTIC:
             fires every attempt until the supervisor shrinks the batch)

* diskfull is transient only because the supervisor's cleanup hook
  (AGENT_HEAL_DISK_FIXED=1) simulates freeing space before resume.
"""

import argparse
import errno
import os
import signal
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from agent_heal import (ProgressWriter, HeartbeatWriter, read_completed,
                        progress_path_from_env)


def cpu_burn(seconds: float) -> None:
    end = time.process_time() + seconds
    x = 0.0
    while time.process_time() < end:
        for i in range(2000):
            x += (i * 0.5) ** 0.5
    return x


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--units", type=int, default=8)
    p.add_argument("--unit-cost", type=float, default=0.3)
    p.add_argument("--batch", type=int, default=64)
    p.add_argument("--mem-limit", type=float, default=1e18)
    p.add_argument("--fault", type=str, default="none",
                   choices=["none", "kill9", "nan", "diskfull", "hang", "oom"])
    p.add_argument("--fault-at", type=int, default=3)
    a = p.parse_args()

    attempt = int(os.environ.get("AGENT_HEAL_ATTEMPT", "0"))
    shrink = float(os.environ.get("AGENT_HEAL_SHRINK", "1.0"))
    disk_fixed = os.environ.get("AGENT_HEAL_DISK_FIXED") == "1"

    batch = a.batch * shrink
    # deterministic OOM: batch doesn't fit -> die like a real OOM
    if a.fault == "oom" and batch > a.mem_limit:
        print("torch.cuda.OutOfMemoryError: CUDA out of memory. "
              f"Tried to allocate batch={batch:.0f} > limit={a.mem_limit:.0f}",
              file=sys.stderr, flush=True)
        sys.exit(137)

    progress = ProgressWriter(progress_path_from_env())
    done = read_completed(progress.path)
    hb = HeartbeatWriter(os.environ.get("AGENT_HEAL_HEARTBEAT",
                                        "/tmp/agent_heal_hb"))
    fault_at = a.fault_at
    fire = (attempt == 0)  # transient faults strike the first attempt only

    for i in range(a.units):
        uid = f"unit-{i}"
        if uid in done:
            print(f"skip {uid} (already complete)", flush=True)
            continue
        # --- fault injection point (before the unit's work) ---
        if fire and i == fault_at:
            if a.fault == "kill9":
                os.kill(os.getpid(), signal.SIGKILL)
            elif a.fault == "nan":
                print(f"metric loss=nan unit={i}", flush=True)
                print("RuntimeError: NaN loss detected, aborting",
                      file=sys.stderr, flush=True)
                sys.exit(1)
            elif a.fault == "diskfull" and not disk_fixed:
                raise OSError(errno.ENOSPC, "No space left on device")
            elif a.fault == "hang":
                print(f"unit {i}: wedging (no more heartbeats)", flush=True)
                while True:
                    time.sleep(60)
        # --- unit of work ---
        cpu_burn(a.unit_cost * shrink)
        loss = 1.0 / (1 + i)
        progress.log({"unit_id": uid, "loss": round(loss, 4),
                      "batch": round(batch, 1)})
        hb.beat()
        print(f"metric loss={loss:.4f} unit={i}", flush=True)

    print("JOB DONE", flush=True)


if __name__ == "__main__":
    main()
