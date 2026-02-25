# Changelog

All notable changes to Runway are documented here.

---

## [0.4.0] — 2026-02-26

### Added
- `command: Optional[list[str]]` field on `JobSpec`: overrides the container entrypoint (`container.command` in K8s, equivalent to Docker `ENTRYPOINT`)
- `args: Optional[list[str]]` field on `JobSpec`: overrides the container arguments (`container.args` in K8s, equivalent to Docker `CMD`)
- Both fields wired into `V1Container` in `k8s_client.py`; Kubernetes accepts `None` so no conditional branching required
- `command` and `args` added to structured log output on job creation

---

## [0.3.0] — 2026-02-25

### Added
- GPU quota reconciler (`quota_reconciler.py`): background async task that polls Kubernetes every 30s and releases in-memory GPU quota when jobs reach a terminal state (SUCCEEDED, FAILED, DEADLINE)
- `QuotaReconciler.register()` called after successful K8s job submission to begin tracking the job
- FastAPI `lifespan` context manager in `main.py` replaces deprecated `@app.on_event`; reconciler started/stopped cleanly with the process
- Job not found in K8s treated as terminal to prevent permanent quota leaks

### Changed
- `main.py` request flow comment updated to include step 6 (reconciler registration)
- In-memory singletons moved above `lifespan` definition for clarity

---

## [0.2.0] — 2026-02-24

### Added
- FastAPI control plane scaffold (`main.py`) with `/jobs`, `/healthz`, and `/metrics` endpoints
- Pydantic request/response schemas (`models.py`): `JobSpec`, `JobSubmitResponse`, `JobStatusResponse`, `JobStatus` enum
- Kubernetes Job creation (`k8s_client.py`): translates validated `JobSpec` into a `batch/v1 Job` manifest; labels jobs with `runway/job-id` for traceability
- Admission control (`admission.py`): enforces per-job CPU, memory, GPU, and timeout bounds; rejects with machine-readable error codes
- Per-tenant GPU quota enforcement (`quota.py`): in-memory counter, thread-safe; quota reserved on submission, rolled back on K8s failure
- Pre-execution cost estimation (`cost.py`): CPU + memory + GPU × timeout model; rates configurable via environment variables
- Per-tenant rate limiting (`rate_limit.py`): fixed-window, thread-safe; 429 response includes `Retry-After` header and `retry_after_s` body field
- Prometheus metrics (`metrics.py`): `jobs_submitted_total`, `jobs_rejected_total` (by reason), `job_creations_total`, `job_create_failures_total`, `job_submission_latency_seconds`
- `failure_reason` surfaced in `GET /jobs/{id}` response: pods listed by `runway/job-id` label; surfaces `OOMKilled`, `DeadlineExceeded`, and `NonZeroExit (exit code N)`
- Structured logging on job submission, admission decisions, K8s API calls, and rejections

### Changed
- Request flow reordered: rate limiting now runs after admission control so malformed requests don't consume per-tenant quota

---

## [0.1.0] — 2026-02-19

### Added
- Initial project commit
- README with project overview
- Documentation scaffold: `project_spec.md`, `architecture.md`, `features.md`, `project_status.md`, `changelog.md`
- Pivoted Runway scope to AI-infrastructure-aware control plane
  - GPU quota enforcement per tenant
  - Cost estimation for CPU, memory, and GPU workloads
  - Admission control for GPU-backed ML training jobs
- `CLAUDE.md` with engineering principles, hard constraints, and collaboration guidelines

---

*Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).*
