"""
quota.py — Per-tenant GPU quota enforcement.

Tracks how many GPUs each tenant currently has reserved across all submitted jobs.
This state lives in memory — it does not survive a process restart.

Why in-memory and not a database?
  Kubernetes is the authoritative source of truth for running jobs.
  In-memory is sufficient for v1 because we're single-replica and single-cluster.
  On restart, quota state could be reconciled by listing active K8s Jobs
  in the namespace (not implemented in v1).
"""

import os
import logging
from threading import Lock

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Configurable per-tenant GPU ceiling (same limit for all tenants in v1).
TENANT_GPU_QUOTA: int = int(os.getenv("TENANT_GPU_QUOTA", "8"))


class GPUQuotaStore:
    """
    Thread-safe in-memory store for per-tenant GPU reservations.

    Structure: { tenant_id -> GPUs currently reserved }

    FastAPI runs in a single process (ASGI, not multi-process by default),
    so a threading.Lock is sufficient. If you ever move to a multi-process
    deployment (e.g. gunicorn with workers), this would need to move to
    Redis or a shared store.
    """

    def __init__(self) -> None:
        self._allocations: dict[str, int] = {}
        self._lock = Lock()

    def check_and_reserve(self, tenant_id: str, gpu_count: int) -> None:
        """
        Atomically check quota and reserve GPUs for a tenant.

        Raises HTTPException 409 if the tenant's reservation would exceed the quota.
        No-op for CPU-only jobs (gpu_count == 0).
        """
        if gpu_count == 0:
            return  # CPU-only jobs don't consume GPU quota

        with self._lock:
            current = self._allocations.get(tenant_id, 0)
            requested_total = current + gpu_count

            if requested_total > TENANT_GPU_QUOTA:
                logger.warning(
                    "GPU quota exceeded",
                    extra={
                        "tenant_id": tenant_id,
                        "allocated": current,
                        "requested": gpu_count,
                        "quota": TENANT_GPU_QUOTA,
                    },
                )
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "GPU_QUOTA_EXCEEDED",
                        "message": (
                            f"GPU quota exceeded for tenant '{tenant_id}': "
                            f"{current} allocated + {gpu_count} requested > {TENANT_GPU_QUOTA} quota"
                        ),
                        "tenant_id": tenant_id,
                        "allocated": current,
                        "requested": gpu_count,
                        "quota": TENANT_GPU_QUOTA,
                    },
                )

            self._allocations[tenant_id] = requested_total
            logger.info(
                "GPU quota reserved",
                extra={
                    "tenant_id": tenant_id,
                    "gpu_count": gpu_count,
                    "total_now": requested_total,
                },
            )

    def release(self, tenant_id: str, gpu_count: int) -> None:
        """
        Release GPUs back to a tenant's quota.

        Used for rollback when K8s submission fails, and later when job completion
        is wired via polling/status reconciliation.
        """
        if gpu_count == 0:
            return

        with self._lock:
            current = self._allocations.get(tenant_id, 0)
            new_total = max(0, current - gpu_count)  # never go negative
            self._allocations[tenant_id] = new_total
            logger.info(
                "GPU quota released",
                extra={
                    "tenant_id": tenant_id,
                    "gpu_count": gpu_count,
                    "total_now": new_total,
                },
            )

    def get_allocated(self, tenant_id: str) -> int:
        """Return the current GPU allocation for a tenant (used for observability)."""
        return self._allocations.get(tenant_id, 0)