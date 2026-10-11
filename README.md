[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) [![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)] [![GitHub stars](https://img.shields.io/github/stars/habib-analyst/agent-heal.svg)]

# agent-heal

Self-healing supervisor for long-running AI agent and training jobs — classify the failure first, then pick the recovery.

Training runs and agent loops die silently: preempted GPUs, OOM-kills, NaN divergences, wedged processes, full disks. The standard response is dumb retry — rerun everything from scratch up to N times and hope. agent-heal classifies the failure first, then chooses the recovery: a SIGKILL resumes from the last checkpoint; a deterministic OOM halves the batch instead of retrying the same doomed size; a stale heartbeat means kill the wedged process and resume. The failure taxonomy learns from every incident, so policy selection improves with experience.

## Quickstart

```bash
git clone https://github.com/habib-analyst/agent-heal.git && cd agent-heal
pip install -e .          # pure stdlib
```

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

Your job speaks a tiny protocol (`agent_heal/checkpoint.py`): read `$AGENT_HEAL_PROGRESS` (JSONL) and skip completed `unit_id`s; append one fsync'd record per completed unit (`ProgressWriter`); touch `$AGENT_HEAL_HEARTBEAT` per unit (`HeartbeatWriter`); honor `$AGENT_HEAL_SHRINK` to scale the work unit down.

## Measured results

Fault-injection benchmark (`bench/`): a synthetic 8-unit job with injected `kill -9`, NaN, disk-full, hang, and deterministic OOM faults, run under agent-heal vs a naive rerun-from-scratch baseline (3 attempts). 30 cells, CPU-only:

| metric | agent-heal | naive baseline |
|---|---|---|
| recovery rate | **100%** (15/15) | 80% (12/15) |
| CPU on transient faults | **~30% less** | — |
| wall-clock recovery, transient faults | **~42% faster** | — |
| deterministic OOM | **3/3** (shrink on first retry) | 0/3 (same size fails identically) |

Unit tests: 35/35. Full writeup: `hidden_files/papers/agent-heal/PAPER.md`.

## How it works

```
job dies → classify (exit code / signal / stderr / metric stream / heartbeat)
        → look up recovery policy in the taxonomy
        → resume | shrink+retry | retry-once | escalate
        → fsync'd incident log → backoff → next attempt
```

| failure | signal | recovery |
|---|---|---|
| `infra_death` | SIGKILL/SIGTERM, no traceback | resume from checkpoint |
| `oom` | exit 137 / "out of memory" | halve batch, resume |
| `nan_divergence` | NaN in metric stream | rewind to last good checkpoint, shrink |
| `disk_full` | ENOSPC | cleanup hook, resume |
| `hang` | heartbeat stale | kill process group, resume |
| `data_error` | missing/corrupt inputs | retry once, then escalate |
| `timeout` | wall budget exceeded | shrink work unit, resume |

Honest limits: the benchmark's faults are synthetic and strike once (except OOM); resume requires job cooperation through the checkpoint protocol — legacy jobs that can't checkpoint get retry-only behavior; heartbeat hang detection trades detection latency against false positives.

Pairs with [agent-autopsy](https://github.com/habib-analyst/agent-autopsy): autopsy diagnoses the dead run; heal keeps the next one alive.

---
Built by [Habib Ur Rehman](https://github.com/habib-analyst) · ML/AI Engineer & healthcare-AI researcher ·
[LinkedIn](https://www.linkedin.com/in/hur-dev) · [habib.top](https://habib.top)
