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

**Per-tenant GPU quota** — The control plane tracks each tenant's total allocated GPU count in memory. A submission is rejected if `tenant_current_gpus + requested_gpu_count > tenant_quota`. The counter increments on successful submission, is rolled back on K8s submission failure, and is released by the background quota reconciler when a job reaches a terminal state (see §7 below).

**Runtime cap** — `timeout` is bounded by a configurable maximum. Jobs requesting a longer wall-clock duration are rejected. The value maps directly to `activeDeadlineSeconds` on the K8s Job.

---

## 3. Rate Limiting

**Per-tenant submission rate** — Each tenant is subject to a configurable maximum submission rate (default: 10 requests per 60-second window). State is in-memory and lost on restart. Configurable via `RATE_LIMIT_REQUESTS` and `RATE_LIMIT_WINDOW_S` environment variables.

**Fixed window** — Time is divided into equal windows. The counter resets at the start of each window. There is no burst allowance — the limit is a hard cap per window. Requests exceeding the limit are rejected immediately; there is no queueing.

**Error semantics** — Rate-limited requests return `429 Too Many Requests`. The response includes a `Retry-After` HTTP header and a `retry_after_s` body field indicating how many seconds remain until the window resets.

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

**OOMKilled** — When a container exceeds its memory limit, the Linux kernel terminates it. Kubernetes records the exit reason as `OOMKilled`. This counts against `backoffLimit`. Runway surfaces this reason in the `failure_reason` field of the job status response.

**Deadline exceeded** — When `activeDeadlineSeconds` elapses, Kubernetes terminates all Pods and marks the Job Failed with reason `DeadlineExceeded`. This is not retried regardless of `backoffLimit`. Runway surfaces this reason in the `failure_reason` field of the job status response.

**Non-zero exit** — Application-level failures are captured by K8s Job failure semantics. Runway surfaces these as `NonZeroExit (exit code N)` in the `failure_reason` field.

`failure_reason` is derived by listing pods for the job via the `runway/job-id` label, picking the most recently terminated pod, and inspecting the container status. The container named `"job"` is preferred; other containers are used as fallback.

Runway does not implement custom watchdogs, requeue logic, or failure callbacks.

---

## 6. GPU Quota Reconciliation

GPU quota is reserved at submission time and released by a background reconciliation loop that runs inside the control plane process.

**Mechanism** — On startup, a `QuotaReconciler` async task is created. Every 30 seconds (configurable via `QUOTA_RECONCILER_INTERVAL_S`) it queries Kubernetes for the status of each tracked GPU job. When a job reaches a terminal state (SUCCEEDED, FAILED, or DEADLINE), it calls `quota_store.release()` and removes the job from the tracker.

**Registration** — After a K8s job is successfully created, `reconciler.register(job_id, tenant_id, gpu_count)` is called on the submission path to begin tracking. CPU-only jobs (gpu_count == 0) are never registered — they hold no GPU quota.

**Failure handling** — If a K8s status query fails for a specific job, that job remains tracked and is retried on the next tick. If a job is no longer found in K8s (e.g., manually deleted), it is treated as terminal and quota is released to prevent permanent leaks. An unhandled exception during a full reconcile tick is logged and does not kill the loop.

**Lifecycle** — The reconciler is started and stopped via the FastAPI `lifespan` context manager, ensuring clean shutdown when the process exits.

**v1 trade-off** — A 30-second polling interval means quota is held for up to 30 seconds after a job finishes. This is acceptable for v1. The Kubernetes Watch API would provide lower latency but adds reconnect/resync complexity.

---

## 7. Observability

**Metrics** — The control plane exposes a Prometheus-compatible `/metrics` endpoint. Tracked signals include: job submissions (total), rejections (by reason), failures (by reason), and submission latency. Metrics are not labeled per-tenant in v1.

**Logs** — The control plane emits structured (JSON) logs for each request, admission decision, K8s API call, and job state transition. Log verbosity is configurable via environment variable.

**Health check** — `GET /healthz` returns `200 OK` when the process is alive. It does not probe K8s connectivity — it is a liveness signal only.
