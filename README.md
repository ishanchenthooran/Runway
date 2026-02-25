# Runway 🛫

Runway is a Kubernetes-native, AI-infrastructure-aware control plane that validates, rate-limits, and cost-estimates batch and ML workloads before submitting them to a shared AWS EKS cluster.

It enforces GPU quotas, runtime caps, and resource bounds to prevent runaway training jobs and GPU starvation, while remaining minimal, Kubernetes-native, and production-inspired.

---

## What Runway Is

Runway is an **internal infrastructure service**, not an end-user product.

It provides:

- A REST API for submitting batch and ML workloads
- API-layer admission control (CPU, memory, GPU, timeout)
- Per-tenant GPU quota enforcement
- Pre-execution cost estimation
- Kubernetes-native retry semantics
- Prometheus-compatible observability

Execution is fully delegated to Kubernetes Jobs.  
Runway does **not** implement a scheduler, queue, or workflow engine.

---

## What Runway Is Not

- ❌ Not a workflow/DAG engine
- ❌ Not a model tracking platform
- ❌ No authentication / RBAC in v1
- ❌ No persistent database
- ❌ No async job queue
- ❌ No multi-cluster or multi-region support
- ❌ No production HA guarantees

Runway is **production-inspired**, not production-hardened.

---

## Architecture Overview

Runway follows a strict **control-plane / data-plane separation**.

### Control Plane

Client (curl / CLI)  
↓  
Runway Control Plane (FastAPI)

Responsibilities:

- Admission control  
- GPU quota enforcement  
- Rate limiting  
- Cost estimation  
- Kubernetes Job creation  

### Data Plane

Runway delegates execution entirely to Kubernetes (EKS).

Kubernetes responsibilities:

- Job scheduling  
- Pod execution  
- Resource enforcement (Linux cgroups)  
- Retry semantics (`backoffLimit`)  
- Runtime caps (`activeDeadlineSeconds`)  

### Observability Layer

Prometheus / Grafana

- Metrics collection  
- Failure visibility  
- Latency tracking  
- Health monitoring  

Kubernetes remains the execution authority.

---

## Job Model

Users submit a minimal `JobSpec`:

- `image`
- `cpu`
- `memory_mb`
- `gpu_count` (optional)
- `timeout_s`
- `tenant_id`

Runway:

1. Validates resource bounds  
2. Enforces GPU quotas  
3. Estimates execution cost  
4. Creates a Kubernetes Job  

Kubernetes is the source of truth for execution state.

---

## AI Infrastructure Guardrails

### GPU Quota Enforcement

Prevents a single tenant from consuming all available GPUs in a shared cluster.

- Per-job maximum GPU limit  
- Per-tenant GPU quota (in-memory, v1)  
- Explicit structured rejection  

### Runtime Caps

Prevents runaway ML training workloads.

- Enforced via `activeDeadlineSeconds`  
- Deadline-exceeded failures surfaced clearly  

### Cost Awareness

Provides visibility before expensive workloads run.

Estimated cost:
(cpu * cpu_rate + memory_gb * mem_rate + gpu * gpu_rate) * runtime_hours


- Rates configurable via environment variables  
- Not integrated with AWS billing APIs in v1  

---

## Observability

### Prometheus Metrics

- `jobs_submitted_total`
- `jobs_rejected_total`
- `gpu_quota_rejected_total`
- `rate_limited_total`
- `job_create_failures_total`
- `request_latency_seconds`

Metrics intentionally avoid per-tenant labels in v1 to prevent cardinality issues.

### Logging

Structured logs include:

- `tenant_id`
- `job_id`
- `request_id`
- `estimated_cost`

### Health Checks

- `/healthz` endpoint

---

## Repository Structure

```text
Runway/
├── docs/
│   ├── project_spec.md      # Canonical requirements and scope
│   ├── architecture.md      # System design and rationale
│   ├── features.md          # Feature inventory and behavior
│   ├── project_status.md    # Milestones and progress
│   └── changelog.md         # Historical changes
│
├── services/
│   └── runway-api/          # FastAPI control plane
│       ├── main.py          # Routes and app entrypoint
│       ├── models.py        # Pydantic request/response schemas
│       ├── admission.py     # Resource bounds validation
│       ├── quota.py         # Per-tenant GPU quota enforcement
│       ├── rate_limit.py    # Per-tenant fixed-window rate limiting
│       ├── cost.py          # Preflight cost estimation
│       ├── k8s_client.py    # Kubernetes Job creation and status
│       ├── metrics.py       # Prometheus metrics definitions
│       └── requirements.txt
│
├── infra/
│   └── terraform/           # AWS + EKS infrastructure (in progress)
│
├── CLAUDE.md                # AI collaboration rules and constraints
└── README.md                # Project overview
```

---

### Design principles

- Kubernetes-native primitives over custom orchestration
- Guardrails over flexibility
- Explicit trade-offs over hidden complexity
- Cost visibility before execution
- AI-infrastructure-aware without becoming an ML platform

---

### Status
The control plane is implemented and functional.
- All core features complete: admission control, GPU quota enforcement, rate limiting, cost estimation, failure reason surfacing
- Observability scaffolded (Prometheus metrics, structured logging)
- Remaining: GPU quota release on job completion, observability stack deployed, EKS provisioning
See `docs/project_status.md` for full milestone tracking.
