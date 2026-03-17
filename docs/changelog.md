# Changelog

All notable changes to Runway are documented here.

---

## [0.8.0] — 2026-03-17

### Added
- Observability stack deployed on local kind cluster (`runway`)
- `kube-prometheus-stack` installed via Helm into `monitoring` namespace
- `k8s/servicemonitor.yaml` applied — Prometheus now scrapes `runway-api` at 15s intervals
- `runway_job_submissions_total` confirmed incrementing in Prometheus after live job submission
- Grafana accessible via port-forward on port 3000; Prometheus data source pre-configured

### Changed
- Runtime target switched from EKS to local kind cluster — same manifests, `imagePullPolicy: Never`, image loaded via `kind load docker-image`
- `k8s/deployment.yaml` updated: image source is local, no ECR required for local dev
- Terraform in `infra/terraform/` retained as production EKS IaC reference (not active)

---

## [0.7.0] — 2026-03-03

### Added
- `kube-prometheus-stack` installed via Helm into `monitoring` namespace on EKS cluster `runway`
- Prometheus, Alertmanager, Grafana, kube-state-metrics, and node-exporter all running in `monitoring` namespace
- Grafana accessible via port-forward (`kubectl port-forward svc/monitoring-grafana 3000:80 -n monitoring`); ships pre-built K8s cluster and node dashboards
- Prometheus accessible via port-forward on port 9090; scraping cluster-level targets (node-exporter, kube-state-metrics)
- Runway API metrics (`/metrics`) not yet wired — ServiceMonitor targeting `runway-api` is next (Mar 3)

---

## [0.6.0] — 2026-03-02

### Added
- `services/runway-api/Dockerfile`: multi-stage Python image; copies source, installs deps from `requirements.txt`, runs uvicorn on port 8000
- `k8s/deployment.yaml`: full control plane manifest — namespaces (`runway`, `runway-jobs`), ServiceAccount, least-privilege Role/RoleBinding scoped to `runway-jobs`, Deployment with liveness probe and resource limits, LoadBalancer Service
- Control plane image built, pushed to ECR (`ca-central-1`), and deployed to EKS cluster `runway`
- `/healthz` confirmed reachable via AWS load balancer external hostname

---

## [0.5.0] — 2026-03-01

### Added
- Terraform infrastructure scaffold (`infra/terraform/`): provisions VPC + EKS cluster on AWS (ca-central-1)
  - `providers.tf`: AWS provider pinned to `~> 5.0`; `default_tags` wires shared tags to all resources
  - `variables.tf`: region, cluster name, Kubernetes version, VPC CIDR, AZ count, node sizing, tags
  - `main.tf`: VPC module (private/public subnets, single NAT gateway); EKS module (managed node group, public API endpoint)
  - `outputs.tf`: cluster name, endpoint, region, `aws eks update-kubeconfig` command
- EKS cluster `runway` live in `ca-central-1` with 2× t3.micro worker nodes

---

## [0.4.1] — 2026-02-26

### Fixed
- Renamed structured log key `"args"` → `"container_args"` in `k8s_client.py`; `args` is a reserved `LogRecord` field in Python's `logging` module and caused a `KeyError` on every job submission

---

## [0.4.0] — 2026-02-26

### Added
- `command: Optional[list[str]]` field on `JobSpec`: overrides the container entrypoint (`container.command` in K8s, equivalent to Docker `ENTRYPOINT`)
- `args: Optional[list[str]]` field on `JobSpec`: overrides the container arguments (`container.args` in K8s, equivalent to Docker `CMD`)
- Both fields wired into `V1Container` in `k8s_client.py`; Kubernetes accepts `None` so no conditional branching required
- `command` and `args` added to structured log output on job creation
- End-to-end smoke test completed: job submission → K8s Job created in `runway-jobs` namespace → status polled successfully

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
