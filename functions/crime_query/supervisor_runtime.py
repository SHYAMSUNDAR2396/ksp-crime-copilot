"""Bounded execution for the typed Catalyst supervisor task graph.

The supervisor selection contract lives in :mod:`supervisor`; this module is
the execution boundary. Specialist handlers receive only the immutable task
context and request payload, return one :class:`EvidenceBundle`, and cannot
pass arbitrary state directly to another specialist. Independent specialists
are fanned out together, then merged evidence is the only input to the
composition boundary.

Catalyst deployments can map this contract to Function fan-out or Circuits.
The local implementation uses a bounded thread pool so the same contract is
deterministically testable without requiring an orchestration service.
"""

import concurrent.futures
import datetime as dt
from dataclasses import dataclass, replace
from typing import Callable, Mapping, Optional, Tuple

try:
    from .evidence import EvidenceBundle, merge_bundles
    from .supervisor import AGENT_SPECS, TaskContext
except ImportError:  # pragma: no cover
    from evidence import EvidenceBundle, merge_bundles
    from supervisor import AGENT_SPECS, TaskContext


AGENT_UNAVAILABLE = "AGENT_UNAVAILABLE"
AGENT_TIMEOUT = "AGENT_TIMEOUT"
AGENT_CONTRACT_INVALID = "AGENT_CONTRACT_INVALID"
COMPOSITION_UNAVAILABLE = "COMPOSITION_UNAVAILABLE"


@dataclass(frozen=True)
class AgentRun:
    agent_name: str
    status: str
    attempts: int
    elapsed_ms: int
    error_code: str = ""
    bundle_id: str = ""


@dataclass(frozen=True)
class TaskGraphResult:
    task_id: str
    merged_evidence: EvidenceBundle
    runs: Tuple[AgentRun, ...]
    failed_agents: Tuple[str, ...]
    complete: bool
    composition: object = None


def _failure_bundle(agent_name, error_code):
    return EvidenceBundle(
        agent_name=agent_name,
        status="unavailable",
        claims=(),
        rows_or_entities=(),
        citations=(),
        evidence_signals=(),
        confidence=0.0,
        limitations=("{0} was unavailable; its evidence was omitted.".format(agent_name),),
        index_or_model_version="unavailable-v1",
        elapsed_ms=0,
    )


def _failure_result(agent_name, error_code, attempts, started):
    elapsed = int(max(0.0, (dt.datetime.now(dt.timezone.utc) - started).total_seconds()) * 1000)
    return (
        _failure_bundle(agent_name, error_code),
        AgentRun(agent_name, "failed", attempts, elapsed, error_code),
    )


def _invoke(agent_name, handler, task, payload, timeout_ms, retry_budget):
    started = dt.datetime.now(dt.timezone.utc)
    attempts = 0
    max_attempts = 1 + max(0, int(retry_budget))
    while attempts < max_attempts:
        attempts += 1
        try:
            bundle = handler(task, payload)
            if not isinstance(bundle, EvidenceBundle) or bundle.agent_name != agent_name:
                return _failure_result(agent_name, AGENT_CONTRACT_INVALID, attempts, started)
            elapsed = int(max(0.0, (dt.datetime.now(dt.timezone.utc) - started).total_seconds()) * 1000)
            if elapsed > timeout_ms:
                return _failure_result(agent_name, AGENT_TIMEOUT, attempts, started)
            return bundle, AgentRun(
                agent_name, "completed", attempts, elapsed, "", bundle.bundle_id,
            )
        except Exception:
            # Provider, SQL, and identity details stay in server-side logs. A
            # client receives only a stable bounded failure code.
            if attempts >= max_attempts:
                return _failure_result(agent_name, AGENT_UNAVAILABLE, attempts, started)
    return _failure_result(agent_name, AGENT_UNAVAILABLE, attempts, started)


def _run_group(task, names, handlers, payload, timeout_override_ms, parallel=True):
    if not parallel:
        bundles, runs = [], []
        for name in names:
            handler = handlers.get(name)
            if handler is None:
                bundle, run = _failure_result(
                    name, AGENT_UNAVAILABLE, 0, dt.datetime.now(dt.timezone.utc),
                )
            else:
                timeout_ms = timeout_override_ms or AGENT_SPECS[name].timeout_ms
                bundle, run = _invoke(
                    name, handler, task, payload, timeout_ms, task.retry_budget,
                )
            bundles.append(bundle)
            runs.append(run)
        return bundles, runs

    futures = {}
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(names)))
    try:
        for name in names:
            handler = handlers.get(name)
            if handler is None:
                futures[name] = None
                continue
            spec = AGENT_SPECS[name]
            timeout_ms = timeout_override_ms or spec.timeout_ms
            futures[name] = executor.submit(
                _invoke, name, handler, task, payload, timeout_ms, task.retry_budget,
            )

        live = {name: future for name, future in futures.items() if future is not None}
        max_timeout = max(
            (timeout_override_ms or AGENT_SPECS[name].timeout_ms for name in live),
            default=0,
        )
        done, _ = concurrent.futures.wait(
            tuple(live.values()), timeout=max_timeout / 1000.0 if max_timeout else 0,
        )
        bundles, runs = [], []
        for name in names:
            future = futures[name]
            if future is None:
                bundle, run = _failure_result(
                    name, AGENT_UNAVAILABLE, 0, dt.datetime.now(dt.timezone.utc),
                )
            elif future not in done:
                future.cancel()
                bundle, run = _failure_result(
                    name, AGENT_TIMEOUT, 1, dt.datetime.now(dt.timezone.utc),
                )
            else:
                try:
                    bundle, run = future.result()
                except Exception:
                    bundle, run = _failure_result(
                        name, AGENT_UNAVAILABLE, 1, dt.datetime.now(dt.timezone.utc),
                    )
            bundles.append(bundle)
            runs.append(run)
        return bundles, runs
    finally:
        # A timed-out provider call is not allowed to block the request path.
        # Catalyst Function/Circuit deployments should enforce the same
        # timeout at the remote invocation boundary.
        executor.shutdown(wait=False)


def _deadline_expired(task):
    deadline = task.deadline
    if deadline is None:
        return False
    if deadline.tzinfo is None:
        now = dt.datetime.now()
    else:
        now = dt.datetime.now(dt.timezone.utc)
    return now >= deadline


def execute_task_graph(
    task: TaskContext,
    handlers: Mapping[str, Callable],
    payload=None,
    composer: Optional[Callable] = None,
    timeout_override_ms=None,
    parallel=True,
):
    """Execute specialist groups, merge evidence, and invoke composition.

    ``handlers`` are keyed by the exact names in ``AGENT_SPECS``. The
    composition callback receives ``(merged_evidence, payload)`` only after
    all selected specialist groups finish. Required-agent failures make the
    result partial even when optional evidence is available.
    """
    if not isinstance(task, TaskContext):
        raise TypeError("task must be a TaskContext")
    if not isinstance(handlers, Mapping):
        raise TypeError("handlers must be a mapping")

    bundles = []
    runs = []
    for group in task.execution_groups:
        specialists = tuple(name for name in group if name != "Composition Agent")
        if not specialists:
            continue
        if _deadline_expired(task):
            for name in specialists:
                bundle, run = _failure_result(
                    name, AGENT_TIMEOUT, 0, dt.datetime.now(dt.timezone.utc),
                )
                bundles.append(bundle)
                runs.append(run)
            continue
        group_bundles, group_runs = _run_group(
            task, specialists, handlers, payload, timeout_override_ms, parallel=parallel,
        )
        bundles.extend(group_bundles)
        runs.extend(group_runs)

    merged = merge_bundles(tuple(bundles))
    failed = tuple(
        run.agent_name for run in runs if run.status != "completed"
    )
    required = set(task.required_agents)
    required_failed = tuple(name for name in required if name in failed)
    composition = None
    composition_failed = False
    if "Composition Agent" in task.selected_agents and composer is not None:
        started = dt.datetime.now(dt.timezone.utc)
        try:
            composition = composer(merged, payload)
            elapsed = int(max(0.0, (dt.datetime.now(dt.timezone.utc) - started).total_seconds()) * 1000)
            runs.append(AgentRun("Composition Agent", "completed", 1, elapsed))
        except Exception:
            composition_failed = True
            runs.append(AgentRun(
                "Composition Agent", "failed", 1, 0, COMPOSITION_UNAVAILABLE,
            ))

    limitations = list(merged.limitations)
    if required_failed:
        limitations.append("A required specialist was unavailable; the result is partial.")
    if composition_failed:
        limitations.append("The composition agent was unavailable; no answer was rendered.")
    if limitations != list(merged.limitations):
        merged = replace(
            merged,
            status="partial" if required_failed or composition_failed else merged.status,
            limitations=tuple(dict.fromkeys(limitations)),
        )

    return TaskGraphResult(
        task_id=task.request_id,
        merged_evidence=merged,
        runs=tuple(runs),
        failed_agents=tuple(dict.fromkeys(failed + required_failed)),
        complete=not required_failed and not composition_failed,
        composition=composition,
    )
