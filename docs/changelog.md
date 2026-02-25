# Changelog

All notable changes to Runway are documented here.

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
