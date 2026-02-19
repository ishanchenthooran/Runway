# Features — Runway

Behavioral reference for Runway's core features. See `docs/project_spec.md` for requirements and `docs/architecture.md` for design rationale.

---

## 1. Job Submission

**Endpoint:** `POST /jobs`

Callers provide: container image, CPU request, memory request, timeout (wall-clock seconds), and optionally `gpu_count`. A `tenant_id` identifies the submitting team.

Runway controls: the Kubernetes Job manifest, resource limits, GPU resource binding, retry count, and deadline. Callers cannot set `backoffLimit`, `activeDeadlineSeconds`, or raw K8s fields directly — these are derived from the validated spec and policy defaults.

On success, the response includes a job ID and cost estimate. Job state is queryable via `GET /jobs/{id}` and listed via `GET /jobs`.

---

## 2. Admission Control

All enforcement occurs synchronously at the API layer before any Kubernetes resource is created. A rejected request returns a `400` with a machine-readable reason.

**CPU and memory bounds** — Each job's CPU and memory requests are checked against configurable per-job maximums. Requests exceeding either bound are rejected.

**GPU per-job maximum** — `gpu_count` is capped at a configurable limit (e.g., 4). Jobs requesting more GPUs than allowed are rejected regardless of tenant quota.

**Per-tenant GPU quota** — The control plane tracks each tenant's total allocated GPU count in memory. A submission is rejected if `tenant_current_gpus + requested_gpu_count > tenant_quota`. The counter increments on successful submission and decrements when the job reaches a terminal state.

**Runtime cap** — `timeout` is bounded by a configurable maximum. Jobs requesting a longer wall-clock duration are rejected. The value maps directly to `activeDeadlineSeconds` on the K8s Job.

---

## 3. Rate Limiting

**Per-tenant submission rate** — Each tenant is subject to a configurable maximum submission rate (e.g., N requests per minute). State is in-memory.

**Burst handling** — A small burst allowance permits short spikes above the steady-state rate. Requests that exceed both the rate and burst are rejected immediately; there is no queueing.

**Error semantics** — Rate-limited requests return `429 Too Many Requests`. The response body identifies the tenant and the limit that was exceeded.

---

## 4. Cost Estimation

Cost is estimated for every job as a preflight step, before K8s Job creation. The estimate is returned in the submission response and is informational — it does not gate or modify the submission.

**Model:**
```
estimated_cost = (cpu_cores   × $/cpu-second
               +  memory_gb   × $/GB-second
               +  gpu_count   × $/gpu-second)
               × timeout_seconds
```

Rates are configured via environment variables with static defaults. The estimate assumes the job runs for its full requested timeout — actual cost may be lower if the job completes early.

There is no real-time AWS billing integration. The model produces a cost signal for awareness, not an invoice.

---

## 5. Retry & Failure Handling

Runway delegates all retry logic to Kubernetes.

**`backoffLimit`** — Set on the K8s Job manifest to a policy default. Kubernetes retries failed Pods up to this count with exponential backoff before marking the Job Failed.

**OOMKilled** — When a container exceeds its memory limit, the Linux kernel terminates it. Kubernetes records the exit reason as `OOMKilled`. This counts against `backoffLimit`. Runway surfaces this reason in the job status response.

**Deadline exceeded** — When `activeDeadlineSeconds` elapses, Kubernetes terminates all Pods and marks the Job Failed with reason `DeadlineExceeded`. This is not retried regardless of `backoffLimit`. Runway surfaces this reason in the job status response.

Runway does not implement custom watchdogs, requeue logic, or failure callbacks.

---

## 6. Observability

**Metrics** — The control plane exposes a Prometheus-compatible `/metrics` endpoint. Tracked signals include: job submissions (total), rejections (by reason), failures (by reason), and submission latency. Metrics are not labeled per-tenant in v1.

**Logs** — The control plane emits structured (JSON) logs for each request, admission decision, K8s API call, and job state transition. Log verbosity is configurable via environment variable.

**Health check** — `GET /healthz` returns `200 OK` when the process is alive. It does not probe K8s connectivity — it is a liveness signal only.
