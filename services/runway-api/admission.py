"""
admission.py — API-layer admission control.

Validates each job spec against per-job resource bounds before any Kubernetes
resources are created. This is the control plane's first line of defense.

Why not Kubernetes admission webhooks?
  Webhooks require TLS infra and a deployed webhook server.
  For a single-cluster internal system, API-layer enforcement is sufficient and
  far simpler to operate. See docs/architecture.md for the full rationale.

Limits are read from environment variables at startup with safe defaults.
Changing a limit requires redeploying the control plane (acceptable for v1).
"""

import os
import logging
from fastapi import HTTPException

from models import JobSpec  # adjust import style later if packaging

logger = logging.getLogger(__name__)

# Per-job resource bounds — configurable via environment variables.
MAX_CPU_CORES: float = float(os.getenv("MAX_CPU_CORES", "8"))
MAX_MEMORY_MB: int = int(os.getenv("MAX_MEMORY_MB", str(32 * 1024)))  # 32 GiB
MAX_GPU_PER_JOB: int = int(os.getenv("MAX_GPU_PER_JOB", "4"))
MAX_TIMEOUT_S: int = int(os.getenv("MAX_TIMEOUT_S", str(3600)))       # 1 hour


def _reject(code: str, message: str, **meta) -> None:
    """
    Standardize admission rejection payloads (machine-readable).
    """
    logger.warning("Admission rejected", extra={"code": code, **meta})
    raise HTTPException(
        status_code=400,
        detail={"code": code, "message": message, **meta},
    )


def check_admission(spec: JobSpec) -> None:
    """
    Validate a job spec against per-job resource bounds.

    Raises HTTPException(400) if any policy bound is violated.
    Returns None if the spec is admissible.

    Note: per-tenant rate limiting is implemented separately (see rate limiting module).
    """
    gpu = getattr(spec, "gpu_count", 0) or 0

    if spec.cpu > MAX_CPU_CORES:
        _reject(
            code="CPU_LIMIT_EXCEEDED",
            message=f"CPU request {spec.cpu} cores exceeds maximum {MAX_CPU_CORES} cores",
            requested=spec.cpu,
            max=MAX_CPU_CORES,
        )

    if spec.memory_mb > MAX_MEMORY_MB:
        _reject(
            code="MEMORY_LIMIT_EXCEEDED",
            message=f"Memory request {spec.memory_mb}MB exceeds maximum {MAX_MEMORY_MB}MB",
            requested=spec.memory_mb,
            max=MAX_MEMORY_MB,
        )

    if gpu > MAX_GPU_PER_JOB:
        _reject(
            code="GPU_LIMIT_EXCEEDED",
            message=f"GPU request {gpu} exceeds per-job maximum {MAX_GPU_PER_JOB}",
            requested=gpu,
            max=MAX_GPU_PER_JOB,
        )

    if spec.timeout_s > MAX_TIMEOUT_S:
        _reject(
            code="TIMEOUT_LIMIT_EXCEEDED",
            message=f"Timeout {spec.timeout_s}s exceeds maximum {MAX_TIMEOUT_S}s",
            requested=spec.timeout_s,
            max=MAX_TIMEOUT_S,
        )

    # NOTE: rate limiting + per-tenant quota enforcement are separate concerns.
    # They should run alongside admission, but kept in their own modules for clarity.