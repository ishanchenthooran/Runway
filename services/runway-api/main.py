"""
main.py — Runway control plane entrypoint.

Thin top layer: routes live here; business logic does not.
Each route delegates immediately to the appropriate module.

Request flow (see docs/architecture.md §Request Flow):
  POST /jobs
    1. Admission control   (admission.py)       — reject bad specs fast, no I/O
    2. Rate limit check    (rate_limit.py)      — in-memory, no I/O
    3. GPU quota check     (quota.py)           — in-memory, no I/O
    4. Cost estimation     (cost.py)            — pure math, no I/O
    5. K8s Job creation    (k8s_client.py)      — only external call in the path
    6. Reconciler register (quota_reconciler.py) — track job for quota release

Start locally:
  uvicorn main:app --reload
"""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from prometheus_client import make_asgi_app

import metrics
from admission import check_admission
from cost import estimate_cost
from diagnostics import DiagnosticsAgent
from k8s_client import KubernetesClient
from models import DiagnosisResponse, JobSpec, JobStatus, JobStatusResponse, JobSubmitResponse
from quota import GPUQuotaStore
from quota_reconciler import QuotaReconciler
from rate_limit import RateLimiter

# Structured logging — swap for structlog or JSON formatter in production.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

# --- In-memory singletons ---
# Constructed once at module load. Acceptable for v1 (single replica, no persistence).
quota_store = GPUQuotaStore()
rate_limiter = RateLimiter()
k8s = KubernetesClient()
reconciler = QuotaReconciler(k8s, quota_store)

# Stores the original JobSpec for each successfully submitted job.
# Used by the diagnostics agent to surface resource requests when explaining failures.
# Lost on restart — consistent with quota state and other in-memory v1 trade-offs.
job_specs: dict[str, JobSpec] = {}

diagnostics_agent = DiagnosticsAgent(k8s, job_specs)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan: runs startup logic before yield, shutdown logic after.

    We start the quota reconciler here so it has access to the running event
    loop. @app.on_event("startup") is deprecated in favour of this pattern.
    """
    await reconciler.start()
    yield
    await reconciler.stop()


app = FastAPI(
    title="Runway Control Plane",
    description="AI-infrastructure-aware batch job submission API",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount Prometheus metrics at /metrics.
app.mount("/metrics", make_asgi_app())


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/healthz", tags=["ops"])
def healthz() -> dict:
    """
    Liveness probe.

    Keep this fast and dependency-free — do not query K8s here.
    """
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Job submission
# ---------------------------------------------------------------------------


@app.post("/jobs", response_model=JobSubmitResponse, status_code=202, tags=["jobs"])
def submit_job(spec: JobSpec) -> JobSubmitResponse:
    """
    Submit a batch job to the Runway control plane.

    Steps:
      1. Admission control  — reject if resource bounds are exceeded
      2. GPU quota check    — reject if tenant would exceed their GPU quota
      3. Cost estimation    — compute worst-case USD cost (informational)
      4. K8s Job creation   — submit a batch/v1 Job to Kubernetes

    Steps 1–3 are pure in-process logic. No K8s API calls occur until step 4.
    A rejection at any earlier step is cheap (no cluster resources touched).
    """
    start = time.monotonic()
    metrics.job_submissions_total.inc()

    logger.info(
        "Job submission received",
        extra={"tenant_id": spec.tenant_id, "image": spec.image},
    )

    try:
        # Step 1: Validate resource bounds (raises HTTPException on violation)
        check_admission(spec)

        # Step 2: Enforce per-tenant submission rate limit (raises HTTPException 429)
        # Runs after admission so malformed requests don't consume quota.
        rate_limiter.check_and_increment(spec.tenant_id)

        # Step 3: Check and reserve per-tenant GPU quota (raises HTTPException on violation)
        quota_store.check_and_reserve(spec.tenant_id, spec.gpu_count)

        # Step 4: Estimate worst-case cost before touching Kubernetes
        estimated_cost = estimate_cost(spec)

        # Step 5: Submit to Kubernetes — first and only external call in this path
        try:
            job_id = k8s.submit_job(spec)
        except Exception:
            # Roll back in-memory quota reservation if K8s submission fails,
            # otherwise tenants can get stuck due to "phantom" reserved GPUs.
            quota_store.release(spec.tenant_id, spec.gpu_count)
            raise

        # Step 6: Register the job with the reconciler so GPU quota is released
        # when the job reaches a terminal state (SUCCEEDED / FAILED / DEADLINE).
        reconciler.register(job_id, spec.tenant_id, spec.gpu_count)

        # Step 7: Store the spec for the diagnostics agent.
        job_specs[job_id] = spec

    except HTTPException as exc:
        # Prefer machine-readable error codes emitted by admission/quota/rate-limit modules.
        reason = "UNKNOWN"
        if isinstance(exc.detail, dict):
            reason = exc.detail.get("code", "UNKNOWN")
        metrics.job_rejections_total.labels(reason=reason).inc()
        raise

    metrics.job_creations_total.inc()
    elapsed = time.monotonic() - start
    metrics.job_submission_latency_seconds.observe(elapsed)

    logger.info(
        "Job submitted successfully",
        extra={
            "job_id": job_id,
            "tenant_id": spec.tenant_id,
            "estimated_cost_usd": estimated_cost,
            "latency_s": round(elapsed, 3),
        },
    )

    return JobSubmitResponse(
        job_id=job_id,
        status=JobStatus.PENDING,
        estimated_cost_usd=estimated_cost,
    )


# ---------------------------------------------------------------------------
# Job status
# ---------------------------------------------------------------------------


@app.get("/jobs/{job_id}", response_model=JobStatusResponse, tags=["jobs"])
def get_job_status(job_id: str) -> JobStatusResponse:
    """
    Query Kubernetes for the current state of a submitted job.

    Runway does not maintain its own job state machine — it delegates
    entirely to the Kubernetes API and translates the result.
    """
    status = k8s.get_job_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return status


# ---------------------------------------------------------------------------
# AI diagnostics
# ---------------------------------------------------------------------------


@app.get("/jobs/{job_id}/diagnose", response_model=DiagnosisResponse, tags=["jobs"])
def diagnose_job(job_id: str) -> DiagnosisResponse:
    """
    Run the AI diagnostics agent against a job.

    The agent uses Claude tool use to query job status and the original spec,
    then produces a natural-language diagnosis and remediation suggestion.

    Intended for failed jobs (FAILED or DEADLINE status), but will run against
    any job ID. Returns 404 if the job does not exist in Kubernetes.
    """
    # Verify the job exists before invoking the agent.
    status = k8s.get_job_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    try:
        diagnosis = diagnostics_agent.diagnose(job_id)
    except Exception as exc:
        logger.exception("Diagnostics agent failed", extra={"job_id": job_id})
        raise HTTPException(status_code=500, detail=f"Diagnostics failed: {exc}") from exc

    metrics.diagnoses_total.inc()

    logger.info("Diagnosis complete", extra={"job_id": job_id})
    return DiagnosisResponse(job_id=job_id, diagnosis=diagnosis)