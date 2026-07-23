"""Redacted operational telemetry for the supervisor execution boundary."""
import json
import logging


LOGGER = logging.getLogger("ksp.crime_copilot")


def task_graph_metric(task, result):
    """Return a value-only metric payload for a completed task graph.

    The supervisor result can contain evidence rows and citations. Telemetry
    deliberately excludes those values and records only operational metadata,
    so Catalyst logs are useful for latency/reliability monitoring without
    becoming a second case-data store.
    """
    runs = tuple(result.runs or ())
    return {
        "event": "task_graph_metric",
        "task_id": str(task.request_id),
        "task_type": str(task.task_type),
        "complete": bool(result.complete),
        "failed_agents": [str(name) for name in result.failed_agents],
        "total_elapsed_ms": sum(max(0, int(run.elapsed_ms)) for run in runs),
        "runs": [
            {
                "agent": str(run.agent_name),
                "status": str(run.status),
                "attempts": max(0, int(run.attempts)),
                "elapsed_ms": max(0, int(run.elapsed_ms)),
                "error_code": str(run.error_code or ""),
            }
            for run in runs
        ],
    }


def emit_task_graph_metric(task, result, logger=LOGGER):
    """Emit one JSON log record and never affect the request result."""
    try:
        logger.info("%s", json.dumps(task_graph_metric(task, result), sort_keys=True))
    except Exception:  # pragma: no cover - defensive logging boundary
        return False
    return True
