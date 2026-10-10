# agent-heal: Self-Healing Supervisor for Long-Running Agent Jobs

Long training runs and agent loops die silently — preempted GPUs, OOM-kills,
NaN divergences, wedged processes, full disks. The standard response is dumb
retry: rerun everything from scratch, up to N times, hoping it works.

**agent-heal classifies the failure first, then picks the recovery.**
A SIGKILL resumes from the last checkpoint; a deterministic OOM halves the
batch instead of retrying the same doomed size; a stale heartbeat means kill
the wedged process and resume; a disk-full cleans up then resumes. The
failure taxonomy learns from every incident, so recovery policy selection
improves with experience.

## The core loop

```
job dies → classify (exit code / stderr / metric stream / heartbeat)
        → look up recovery policy in the taxonomy
        → resume | shrink+retry | retry-once | escalate
        → fsync'd incident log → backoff → next attempt
```

## Quick start

```python
from agent_heal import Supervisor

sup = Supervisor(incident_log="incidents.jsonl")
result = sup.run(
    ["python3", "train.py", "--epochs", "50"],
    job_id="exp-42",
    run_dir="runs/exp-42",   # progress.jsonl + heartbeat live here
)
print(result.recovered, result.attempts, result.total_cpu_s)
```

Your job speaks a tiny protocol (see `agent_heal/checkpoint.py`):
- read `$AGENT_HEAL_PROGRESS` (JSONL), skip completed `unit_id`s
- append one fsync'd record per completed unit (`ProgressWriter`)
- touch `$AGENT_HEAL_HEARTBEAT` per unit (`HeartbeatWriter`)
- honor `$AGENT_HEAL_SHRINK` to scale the work unit down

## Failure classes → recovery policies

| Failure | Signal | Recovery |
|---|---|---|
| `infra_death` | SIGKILL/SIGTERM, no traceback | resume from checkpoint |
| `oom` | exit 137 / "out of memory" | halve batch, resume |
| `nan_divergence` | NaN in metric stream | rewind to last good checkpoint, shrink |
| `disk_full` | ENOSPC | cleanup hook, resume |
| `hang` | heartbeat stale | kill process group, resume |
| `data_error` | missing/corrupt inputs | retry once, then escalate |
| `timeout` | wall budget exceeded | shrink work unit, resume |

## Benchmark

`bench/` contains a fault-injection benchmark: a synthetic 8-unit job with
injected `kill -9`, NaN, disk-full, hang, and deterministic OOM faults,
run under agent-heal vs a naive rerun-from-scratch baseline (3 attempts).

```
python3 bench/run_benchmark.py
```

Measured on CPU (see `hidden_files/papers/agent-heal/PAPER.md` for the full
writeup): **100% vs 80% recovery rate** (15/15 vs 12/15 faulted jobs), **~30%
less CPU burned** and **~42% faster wall-clock recovery** on transient faults
by resuming instead of redoing completed units. Deterministic OOM is
unrecoverable for naive retry (0/3 — same size fails identically) and
recovered on the first shrink by agent-heal (3/3).

## Layout

```
agent_heal/      the package: supervisor, classifier, taxonomy,
                 policies, checkpoint protocol, heartbeat, incident log
bench/           synthetic_job.py (fault injection) + run_benchmark.py
tests/           pytest suite (35 tests)
```

## License

MIT — see LICENSE.
