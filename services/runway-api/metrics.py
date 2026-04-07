"""
metrics.py — Prometheus metrics for the Runway control plane.

Defines all counters and histograms. These are module-level singletons —
prometheus_client registers them globally on import.

In v1, metrics are NOT labeled per-tenant (see project_spec.md §Observability).
Tenant-level debugging happens via structured logs, not metric dimensions.

The /metrics HTTP endpoint is mounted in main.py using prometheus_client's
ASGI app — no separate metrics server needed.
"""

from prometheus_client import Counter, Histogram

# --- Submission lifecycle ---

job_submissions_total = Counter(
    "runway_job_submissions_total",
    "Total number of job submission requests received by the control plane",
)

job_rejections_total = Counter(
    "runway_job_rejections_total",
    "Total number of jobs rejected before reaching Kubernetes",
    # 'reason' distinguishes policy violations so operators can see what's being hit most.
    # e.g. CPU_LIMIT_EXCEEDED, GPU_QUOTA_EXCEEDED, RATE_LIMITED
    labelnames=["reason"],
)

job_creations_total = Counter(
    "runway_job_creations_total",
    "Total number of Kubernetes Jobs successfully created",
)

# --- Job outcomes (sourced from K8s, not submission) ---

job_failures_total = Counter(
    "runway_job_failures_total",
    "Total number of jobs that reached a failed terminal state in Kubernetes",
    # 'reason' maps to K8s failure signals: OOMKilled, DeadlineExceeded, NonZeroExit
    labelnames=["reason"],
)

# --- AI diagnostics ---

diagnoses_total = Counter(
    "runway_diagnoses_total",
    "Total number of AI diagnostic requests handled by the diagnose endpoint",
)

# --- Latency ---

job_submission_latency_seconds = Histogram(
    "runway_job_submission_latency_seconds",
    "End-to-end latency of the POST /jobs handler (validation + K8s Job creation)",
    # Buckets tuned to the 500ms SLO from project_spec.md §Non-Functional Requirements.
    buckets=[0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)
