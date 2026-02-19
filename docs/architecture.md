# Architecture — Runway

---

## Control Plane / Data Plane Separation

Runway is split into two distinct layers:

**Control Plane** — a single-replica FastAPI service responsible for:
- Receiving and validating job submissions
- Enforcing admission control (CPU, memory, GPU, timeout bounds; per-tenant GPU quota)
- Applying per-tenant rate limiting
- Performing cost estimation before any K8s resource is created
- Issuing `batch/v1 Job` manifests to the Kubernetes API
- Exposing job status, metrics, and health endpoints

**Data Plane** — Kubernetes primitives responsible for:
- Scheduling and executing Job Pods on cluster nodes
- Enforcing resource limits via Linux cgroups (CPU throttling, memory OOM)
- GPU assignment via the NVIDIA device plugin (`nvidia.com/gpu` resource)
- Retry behavior via `backoffLimit` on the Job spec
- Surfacing terminal state (Succeeded, Failed, OOMKilled, DeadlineExceeded) to the control plane via the K8s API

The control plane never executes workloads. The data plane never validates or prices requests. There is no shared state between them beyond the Kubernetes API.

---

## Request Flow

```
Client
  │
  ▼
POST /jobs
  │
  ├─ [1] Input validation
  │       Deserialize and type-check the job spec (image, cpu, memory, gpu_count, timeout)
  │
  ├─ [2] Admission control
  │       Reject if any per-job bound is exceeded (max CPU, memory, GPU, timeout)
  │       Reject if tenant GPU quota would be exceeded (in-memory counter)
  │       Reject if tenant submission rate limit is exceeded (in-memory token bucket or sliding window)
  │
  ├─ [3] Cost estimation
  │       Compute estimated cost:
  │         cpu_cost    = cpu_cores   × timeout_seconds × $/cpu-second
  │         memory_cost = memory_gb   × timeout_seconds × $/GB-second
  │         gpu_cost    = gpu_count   × timeout_seconds × $/gpu-second
  │       Total estimate is returned in the response. No K8s resources exist yet at this point.
  │
  ├─ [4] K8s Job creation
  │       Build a batch/v1 Job manifest:
  │         - resource requests and limits from validated spec
  │         - nvidia.com/gpu limit if gpu_count > 0
  │         - activeDeadlineSeconds from timeout
  │         - backoffLimit from policy defaults
  │       Submit via the kubernetes Python client
  │
  └─ [5] Response
          Return job ID, estimated cost, and initial status to the client
```

Steps 1–3 are pure in-process logic. No K8s API calls occur until step 4. A rejection at any earlier step is cheap.

---

## Admission Control Detail

Admission control runs entirely at the API layer. Kubernetes admission webhooks are out of scope for v1 — they require TLS infrastructure, a separately deployed webhook server, and introduce latency in the K8s API path. API-layer enforcement is sufficient for a single-cluster, internal-only system.

### Per-job bounds (static policy)

| Resource   | Enforced limit            |
|------------|---------------------------|
| CPU        | Configurable max (e.g., 8 cores) |
| Memory     | Configurable max (e.g., 32Gi)    |
| GPU        | Configurable max per job (e.g., 4) |
| Timeout    | Configurable max wall-clock (e.g., 1h) |

### Per-tenant GPU quota (in-memory)

The control plane maintains a dict of `tenant_id → gpu_currently_allocated`. On each submission, it checks whether adding the requested `gpu_count` would exceed the tenant's configured quota. On job completion or failure, the counter is decremented.

This state is lost on process restart. Kubernetes remains the source of truth for running jobs — on startup, the control plane can optionally reconcile by listing active Jobs in the namespace.

### Rate limiting (in-memory)

Per-tenant submission rate is enforced using a sliding window or token bucket. Tenants are identified by a header (`X-Tenant-ID`) or request body field — no authentication backs this in v1. Rate limit state is in-process and lost on restart.

---

## Cost Estimation

Cost estimation is a preflight step that runs before K8s Job creation. Rates are configurable via environment variables with hardcoded defaults:

```
COST_CPU_PER_CPU_SECOND     (default: 0.000048 $/cpu-second)
COST_MEMORY_PER_GB_SECOND   (default: 0.000006 $/GB-second)
COST_GPU_PER_GPU_SECOND     (default: 0.00028  $/gpu-second)
```

The estimate reflects the worst-case cost if the job runs for its full `timeout`. It is informational — it does not gate submission in v1. The estimate is returned in the API response alongside the job ID.

---

## State Model

Runway holds no persistent state. In-memory state consists of:

- Per-tenant GPU allocation counters
- Per-tenant rate limit windows

Kubernetes is the authoritative source of truth for job state. The control plane derives job status by querying the K8s API on demand (GET /jobs, GET /jobs/{id}). There is no background reconciliation loop in v1.

```
K8s Job states surfaced by Runway:

  PENDING     → Pod not yet scheduled
  RUNNING     → Pod executing
  SUCCEEDED   → Pod exited 0
  FAILED      → Pod exited non-zero (includes OOMKilled, user error)
  DEADLINE    → activeDeadlineSeconds exceeded (K8s sets reason: DeadlineExceeded)
```

---

## Failure Modes

### OOMKilled
The Linux kernel OOM killer terminates the container when it exceeds its memory limit. Kubernetes records the exit reason as `OOMKilled` in the Pod status. Runway surfaces this in the job status response. The K8s Job will retry up to `backoffLimit` times before entering Failed state.

### Deadline Exceeded
When a Job's `activeDeadlineSeconds` elapses, Kubernetes terminates all Pods and marks the Job Failed with reason `DeadlineExceeded`. Runway surfaces this reason. No custom timeout watchdog is needed.

### Non-zero Exit / Application Error
Captured by K8s Job failure semantics. `backoffLimit` controls retry count. Runway does not implement custom retry logic.

### Control Plane Crash
The FastAPI process is stateless with respect to K8s. Running Jobs continue to execute in the data plane unaffected. In-memory state (GPU quota counters, rate limit windows) is lost. On restart, the control plane can reconcile GPU counters by listing active Jobs. There is no HA — a single-replica Deployment is acceptable for v1.

### K8s API Unavailable
Job submission fails fast. The control plane returns a 503. No retry is attempted — callers are expected to retry at the client level. Job status queries similarly fail fast.

---

## Deployment

```
AWS EKS (single region, single cluster)
  └── jobs namespace
        ├── Deployment: runway-api (1 replica)
        │     image: runway/control-plane
        │     env: COST_* rates, K8s in-cluster auth
        │     ports: 8000 (HTTP)
        └── Jobs: <submitted batch jobs>
              resource limits from validated spec
              nvidia.com/gpu if gpu_count > 0
```

Infrastructure is provisioned via Terraform (`infra/terraform/`). The control plane authenticates to the Kubernetes API using in-cluster service account credentials. No external load balancer or ingress is required for v1 — internal access only.

---

## What Is Explicitly Out of Scope (v1)

| Omitted component              | Reason |
|-------------------------------|--------|
| Persistent database            | In-memory state is sufficient; K8s is source of truth |
| Async job queue                | Synchronous submission is simpler and sufficient |
| K8s admission webhooks         | Requires TLS infra; API-layer enforcement is adequate |
| HA / multi-replica control plane | Single replica acceptable for internal, demo-scale use |
| Pod log streaming              | Adds complexity; kubectl logs is sufficient for v1 |
| Real AWS cost integration      | Configurable rate model is sufficient for cost visibility |
| Authentication / RBAC          | Out of scope for v1 |
| Multi-cluster / multi-region   | Single cluster is the explicit constraint |
