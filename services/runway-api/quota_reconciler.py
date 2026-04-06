"""
quota_reconciler.py — Background reconciliation of GPU quota against live K8s state.

## Why this exists

GPU quota is reserved at job submission time but never automatically released.
Without a release mechanism, the in-memory quota store drains to zero as jobs
complete, and new submissions are rejected even though cluster capacity is free.

## Design: pull-based reconciliation (not push)

Kubernetes does not call back when a job finishes. Instead of using the K8s
Watch API (complex reconnect/resync logic), we use a simple polling loop:

  every POLL_INTERVAL_S seconds:
    for each tracked active job:
      query K8s for its current status
      if terminal (SUCCEEDED, FAILED, DEADLINE): release quota + stop tracking

This is the reconciliation pattern: periodically compare expected state
(in-memory tracker) against actual state (K8s) and correct divergence.

## Async safety

KubernetesClient methods are synchronous (blocking HTTP). Calling them
directly from an async context would block the event loop. We use
asyncio.to_thread() to offload each K8s call to a thread-pool worker.

## Locking strategy

_active_jobs is mutated by two paths:
  - register()     — called from the sync submit_job route, which FastAPI runs
                     in a thread-pool worker. Cannot await an asyncio.Lock.
                     Uses a plain dict write, which the GIL makes atomic.
  - _reconcile()   — runs on the event loop. Uses asyncio.Lock to make the
                     snapshot and pop atomic with respect to other async tasks.

quota.py's threading.Lock is unchanged — it's correct for its own sync callers.
"""

import asyncio
import logging
import os

import metrics
from k8s_client import KubernetesClient
from models import JobStatus
from quota import GPUQuotaStore

logger = logging.getLogger(__name__)

POLL_INTERVAL_S: int = int(os.getenv("QUOTA_RECONCILER_INTERVAL_S", "30"))

# Terminal states — once a job reaches one of these, it will never run again.
_TERMINAL_STATUSES = {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.DEADLINE}


class QuotaReconciler:
    """
    Background task that periodically reconciles in-memory GPU quota
    against live Kubernetes job state.

    Lifecycle:
      start()    → called at FastAPI startup, kicks off the poll loop
      stop()     → called at FastAPI shutdown, cancels the poll loop cleanly

    Registration:
      register() → called after successful K8s submission to track a job.
                   CPU-only jobs (gpu_count == 0) are ignored.
    """

    def __init__(self, k8s: KubernetesClient, quota_store: GPUQuotaStore) -> None:
        self._k8s = k8s
        self._quota_store = quota_store

        # job_id → (tenant_id, gpu_count)
        # Populated by register() on the main request path.
        # Drained by _reconcile() when jobs reach a terminal state.
        self._active_jobs: dict[str, tuple[str, int]] = {}

        # asyncio.Lock: guards snapshot + pop inside the async reconcile path.
        # Not used in register() — see module docstring for rationale.
        self._lock = asyncio.Lock()

        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Public: registration
    # ------------------------------------------------------------------

    def register(self, job_id: str, tenant_id: str, gpu_count: int) -> None:
        """
        Begin tracking a job for quota release.

        Called synchronously on the job submission path (FastAPI thread-pool
        worker) after the K8s job has been created successfully. The plain
        dict write is GIL-atomic; no async lock needed here. CPU-only jobs
        (gpu_count == 0) are skipped — they hold no GPU quota.
        """
        self._active_jobs[job_id] = (tenant_id, gpu_count)

        logger.info(
            "Reconciler: tracking job for quota release",
            extra={"job_id": job_id, "tenant_id": tenant_id, "gpu_count": gpu_count},
        )

    # ------------------------------------------------------------------
    # Public: lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Spawn the background poll loop. Called at FastAPI startup."""
        self._task = asyncio.create_task(self._poll_loop(), name="quota-reconciler")
        logger.info(
            "Quota reconciler started",
            extra={"poll_interval_s": POLL_INTERVAL_S},
        )

    async def stop(self) -> None:
        """Cancel the poll loop and wait for it to exit. Called at FastAPI shutdown."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Quota reconciler stopped")

    # ------------------------------------------------------------------
    # Internal: polling
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """
        Infinite loop: sleep → reconcile → repeat.

        Sleeps first so a fresh startup doesn't immediately hit K8s before
        any jobs have been registered.
        """
        while True:
            await asyncio.sleep(POLL_INTERVAL_S)
            try:
                await self._reconcile()
            except Exception:
                # Never let a reconcile error kill the loop.
                # Log and continue — next tick will retry.
                logger.exception("Quota reconciler: unexpected error during reconcile")

    async def _reconcile(self) -> None:
        """
        Snapshot active jobs, query K8s for each, release quota for terminals.

        asyncio.to_thread() offloads the blocking K8s call off the event loop.
        The asyncio.Lock ensures the snapshot is consistent with any concurrent
        _release_and_untrack() calls issued in the same tick.
        """
        async with self._lock:
            snapshot = dict(self._active_jobs)

        if not snapshot:
            return

        logger.debug(
            "Quota reconciler: reconcile tick",
            extra={"active_job_count": len(snapshot)},
        )

        for job_id, (tenant_id, gpu_count) in snapshot.items():
            try:
                status_response = await asyncio.to_thread(
                    self._k8s.get_job_status, job_id
                )
            except Exception:
                logger.exception(
                    "Quota reconciler: failed to fetch job status",
                    extra={"job_id": job_id},
                )
                continue  # leave the job tracked, retry next tick

            if status_response is None:
                # Job not found in K8s — treat as terminal to avoid leaking quota.
                logger.warning(
                    "Quota reconciler: job not found in K8s, releasing quota",
                    extra={"job_id": job_id, "tenant_id": tenant_id},
                )
                await self._release_and_untrack(job_id, tenant_id, gpu_count)
                continue

            if status_response.status in _TERMINAL_STATUSES:
                logger.info(
                    "Quota reconciler: job terminal, releasing quota",
                    extra={
                        "job_id": job_id,
                        "tenant_id": tenant_id,
                        "status": status_response.status,
                        "gpu_count": gpu_count,
                    },
                )
                if status_response.status in {JobStatus.FAILED, JobStatus.DEADLINE}:
                    reason = status_response.failure_reason or status_response.status.value
                    metrics.job_failures_total.labels(reason=reason).inc()
                await self._release_and_untrack(job_id, tenant_id, gpu_count)

    async def _release_and_untrack(
        self, job_id: str, tenant_id: str, gpu_count: int
    ) -> None:
        """Release GPU quota and remove the job from the tracker atomically."""
        self._quota_store.release(tenant_id, gpu_count)
        async with self._lock:
            self._active_jobs.pop(job_id, None)
