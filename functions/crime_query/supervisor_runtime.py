"""Bounded execution for the typed Catalyst supervisor task graph.

The supervisor selection contract lives in :mod:`supervisor`; this module is
the execution boundary. Specialist handlers receive only the immutable task
context and request payload, return one :class:`EvidenceBundle`, and cannot
pass arbitrary state directly to another specialist. Independent specialists
are fanned out together, then merged evidence is the only input to the
composition boundary.

Catalyst deployments can map this contract to Function fan-out or Circuits.
The local implementation uses a bounded thread pool so the same contract is
deterministically testable without requiring an orchestration service. Every
specialist and composition wait is bounded by the smaller of its agent timeout
and the task's total deadline.
"""

import concurrent.futures
import datetime as dt
from dataclasses import dataclass, replace
from typing import Callable, Mapping, Optional, Tuple

try:
    from .evidence import EvidenceBundle, merge_bundles
    from .observability import emit_task_graph_metric
    from .supervisor import AGENT_SPECS, TaskContext
except ImportError:  # pragma: no cover
    from evidence import EvidenceBundle, merge_bundles
    from observability import emit_task_graph_metric
    from supervisor import AGENT_SPECS, TaskContext


AGENT_UNAVAILABLE = "AGENT_UNAVAILABLE"
AGENT_TIMEOUT = "AGENT_TIMEOUT"
AGENT_CONTRACT_INVALID = "AGENT_CONTRACT_INVALID"
COMPOSITION_UNAVAILABLE = "COMPOSITION_UNAVAILABLE"


def parallel_for_backend(db):
    """Select safe fan-out mode for the injected persistence adapter.

    ``SqliteDB`` owns a thread-bound connection and must remain inline. The
    Catalyst ``ZcqlDB`` adapter has no thread-bound connection and uses the
    bounded worker path, which is the deployment equivalent of specialist
    Function fan-out while retaining one request-scoped deadline.
    """
    return not hasattr(db, "_conn")


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
                configured_timeout = timeout_override_ms or AGENT_SPECS[name].timeout_ms
                timeout_ms = _bounded_timeout_ms(task, configured_timeout)
                if timeout_ms <= 0:
                    bundle, run = _failure_result(
                        name, AGENT_TIMEOUT, 0, dt.datetime.now(dt.timezone.utc),
                    )
                else:
                    bundle, run = _invoke(
                        name, handler, task, payload, timeout_ms, task.retry_budget,
                    )
            bundles.append(bundle)
            runs.append(run)
        return bundles, runs

    futures = {}
    timeouts = {}
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(names)))
    try:
        for name in names:
            handler = handlers.get(name)
            if handler is None:
                futures[name] = None
                continue
            spec = AGENT_SPECS[name]
            timeout_ms = _bounded_timeout_ms(
                task, timeout_override_ms or spec.timeout_ms,
            )
            timeouts[name] = timeout_ms
            if timeout_ms <= 0:
                futures[name] = None
                continue
            futures[name] = executor.submit(
                _invoke, name, handler, task, payload, timeout_ms, task.retry_budget,
            )

        live = {name: future for name, future in futures.items() if future is not None}
        max_timeout = max(
            (timeouts[name] for name in live),
            default=0,
        )
        done, _ = concurrent.futures.wait(
            tuple(live.values()), timeout=max_timeout / 1000.0 if max_timeout else 0,
        )
        bundles, runs = [], []
        for name in names:
            future = futures[name]
            if future is None:
                error_code = (
                    AGENT_TIMEOUT if timeouts.get(name, 0) <= 0 else AGENT_UNAVAILABLE
                )
                bundle, run = _failure_result(
                    name, error_code, 0, dt.datetime.now(dt.timezone.utc),
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
    remaining = _remaining_ms(task)
    return remaining is not None and remaining <= 0


def _remaining_ms(task):
    """Return the task's remaining budget, or ``None`` when unbounded."""
    deadline = task.deadline
    if deadline is None:
        return None
    if deadline.tzinfo is None:
        now = dt.datetime.now()
    else:
        now = dt.datetime.now(dt.timezone.utc)
    return max(0, int((deadline - now).total_seconds() * 1000))


def _bounded_timeout_ms(task, configured_timeout_ms):
    remaining = _remaining_ms(task)
    if remaining is None:
        return configured_timeout_ms
    return min(configured_timeout_ms, remaining)


def _run_composition(task, composer, merged, payload, timeout_override_ms, parallel):
    """Run composition with the same bounded contract as specialists.

    SQLite's connection is thread-bound, so inline mode measures and rejects
    an over-budget composition after it returns. Catalyst/parallel mode uses
    an isolated worker and returns at the deadline without waiting for a
    provider call that cannot be cancelled locally.
    """
    configured_timeout = timeout_override_ms or AGENT_SPECS["Composition Agent"].timeout_ms
    timeout_ms = _bounded_timeout_ms(task, configured_timeout)
    started = dt.datetime.now(dt.timezone.utc)
    if timeout_ms <= 0:
        return None, AgentRun("Composition Agent", "failed", 0, 0, AGENT_TIMEOUT)

    if not parallel:
        try:
            composition = composer(merged, payload)
        except Exception:
            return None, AgentRun("Composition Agent", "failed", 1, 0, COMPOSITION_UNAVAILABLE)
        elapsed = int(max(0.0, (dt.datetime.now(dt.timezone.utc) - started).total_seconds()) * 1000)
        if elapsed > timeout_ms:
            return None, AgentRun("Composition Agent", "failed", 1, elapsed, AGENT_TIMEOUT)
        return composition, AgentRun("Composition Agent", "completed", 1, elapsed)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(composer, merged, payload)
    try:
        try:
            composition = future.result(timeout=timeout_ms / 1000.0)
        except concurrent.futures.TimeoutError:
            future.cancel()
            elapsed = int(max(0.0, (dt.datetime.now(dt.timezone.utc) - started).total_seconds()) * 1000)
            return None, AgentRun("Composition Agent", "failed", 1, elapsed, AGENT_TIMEOUT)
        except Exception:
            elapsed = int(max(0.0, (dt.datetime.now(dt.timezone.utc) - started).total_seconds()) * 1000)
            return None, AgentRun("Composition Agent", "failed", 1, elapsed, COMPOSITION_UNAVAILABLE)
        elapsed = int(max(0.0, (dt.datetime.now(dt.timezone.utc) - started).total_seconds()) * 1000)
        return composition, AgentRun("Composition Agent", "completed", 1, elapsed)
    finally:
        executor.shutdown(wait=False)


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
        composition, composition_run = _run_composition(
            task, composer, merged, payload, timeout_override_ms, parallel,
        )
        composition_failed = composition_run.status != "completed"
        runs.append(composition_run)

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

    composition_failed_agents = ("Composition Agent",) if composition_failed else ()
    result = TaskGraphResult(
        task_id=task.request_id,
        merged_evidence=merged,
        runs=tuple(runs),
        failed_agents=tuple(dict.fromkeys(failed + required_failed + composition_failed_agents)),
        complete=not required_failed and not composition_failed,
        composition=composition,
    )
    emit_task_graph_metric(task, result)
    return result
