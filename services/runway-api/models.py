"""
models.py — Pydantic schemas for Runway's API surface.

This is the leaf module: it imports nothing from this project.
Every other module can safely import from here without circular dependencies.

Design principles:
- Keep API contracts explicit and minimal.
- No hidden defaults that affect infrastructure behavior.
- Status values map directly to Kubernetes semantics.
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Job lifecycle status
# ---------------------------------------------------------------------------

class JobStatus(str, Enum):
    """
    High-level job states exposed by Runway.

    These are translations of Kubernetes Job/Pod state.
    Runway does NOT maintain its own scheduler or state machine.
    """

    PENDING = "PENDING"       # Job accepted but not yet running
    RUNNING = "RUNNING"       # Pod is active
    SUCCEEDED = "SUCCEEDED"   # Job completed successfully
    FAILED = "FAILED"         # Job failed (non-zero exit, OOM, etc.)
    DEADLINE = "DEADLINE"     # Exceeded activeDeadlineSeconds


# ---------------------------------------------------------------------------
# Job submission payload
# ---------------------------------------------------------------------------

class JobSpec(BaseModel):
    """
    Client-provided job specification.

    tenant_id is unverified in v1 (no authentication system).
    It is used only for:
      - GPU quota enforcement
      - rate limiting (later)
      - logging and observability

    All resource fields are validated here for basic positivity,
    but upper bounds are enforced in admission.py.
    """

    image: str = Field(
        ...,
        min_length=1,
        description="Container image to run (e.g. 'pytorch/pytorch:2.0.0')",
    )

    cpu: float = Field(
        ...,
        gt=0,
        description="CPU cores to request and limit",
    )

    memory_mb: int = Field(
        ...,
        gt=0,
        description="Memory in MB (mapped to Mi in Kubernetes manifest)",
    )

    gpu_count: int = Field(
        0,
        ge=0,
        description="Number of GPUs required (0 = CPU-only job)",
    )

    timeout_s: int = Field(
        ...,
        gt=0,
        description="Max wall-clock time in seconds (maps to activeDeadlineSeconds)",
    )

    tenant_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Caller-supplied tenant identifier (unauthenticated in v1)",
    )

    command: Optional[list[str]] = Field(
        None,
        description=(
            "Override the container entrypoint (maps to Kubernetes container.command, "
            "which overrides the Docker ENTRYPOINT). If omitted, the image default is used."
        ),
    )

    args: Optional[list[str]] = Field(
        None,
        description=(
            "Override the container arguments (maps to Kubernetes container.args, "
            "which overrides the Docker CMD). If omitted, the image default is used."
        ),
    )


# ---------------------------------------------------------------------------
# Job submission response
# ---------------------------------------------------------------------------

class JobSubmitResponse(BaseModel):
    """
    Returned by POST /jobs on successful admission.

    The job is initially PENDING until Kubernetes schedules a Pod.
    estimated_cost_usd reflects the worst-case cost if the job
    runs for its full timeout.
    """

    job_id: str
    status: JobStatus = JobStatus.PENDING
    estimated_cost_usd: Optional[float] = None


# ---------------------------------------------------------------------------
# Job status response
# ---------------------------------------------------------------------------

class JobStatusResponse(BaseModel):
    """
    Returned by GET /jobs/{job_id}.

    Status is derived from Kubernetes Job state.
    Runway does not track execution state independently.

    failure_reason surfaces Kubernetes-level signals such as:
      - OOMKilled
      - DeadlineExceeded
      - NonZeroExit
    """

    job_id: str
    status: JobStatus
    tenant_id: str
    failure_reason: Optional[str] = None