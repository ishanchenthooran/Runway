# Project Specification — Runway

> This is the authoritative source of truth for Runway's requirements and scope.
> Other docs may summarize, but this file is authoritative.

---

## Problem Statement

Internal engineering teams need to run batch workloads — including ML training jobs —
on shared Kubernetes infrastructure. Without guardrails, individual jobs
can starve cluster resources (especially GPUs), fail silently, or run indefinitely with no cost visibility.

Runway provides a thin, AI-infrastructure-aware control plane that accepts, validates, and submits batch jobs
to Kubernetes while enforcing resource limits (CPU, memory, GPU), rate limiting, and cost awareness.

---

## Target Users

- Internal engineering teams submitting batch workloads
- Platform operators monitoring cluster health and job outcomes
- No external or end-user access

---

## Functional Requirements (v1)

### Job Submission
- Accept job specs via REST API (container image, resource requests, timeout, optional `gpu_count`)
- Validate specs against admission policy before creating K8s resources
- When `gpu_count > 0`, the resulting Kubernetes Job must request `nvidia.com/gpu`
- Return a job identifier on successful submission
- Support job status queries and listing
- Job status reflects Kubernetes Job/Pod state; Runway does not maintain an independent scheduler or state machine

### Admission Control
- Enforce per-job bounds on CPU, memory, GPU, and wall-clock timeout
- Enforce per-job max GPU limit (e.g., 4 GPUs)
- Enforce simple per-tenant GPU quota (in-memory, no persistence)
- Reject jobs that exceed configured limits with clear error messages
- All validation happens at the API layer (no K8s admission webhooks in v1)
- *No real GPU cluster required for v1; enforcement is design-level only*

### Rate Limiting
- Enforce per-tenant submission rate limits
- *Assumption: tenants are identified by a simple identifier passed in the request
  (e.g., a header or field) — no authentication system backs this in v1*

### Cost Estimation
- Estimate job cost before submission based on requested resources (CPU, memory, GPU) and timeout
- Surface cost estimate in the API response
- *Assumption: cost model uses configurable $/cpu-second, $/GB-second, and $/gpu-second rates —
  not tied to real AWS billing APIs in v1*

### Retry and Failure Handling
- Use Kubernetes-native retry semantics (`backoffLimit` on Job spec)
- Surface failure reasons from K8s (OOMKilled, deadline exceeded, non-zero exit)
- Do not implement custom retry orchestration

### Observability
- Structured logging from the control plane
- Prometheus-compatible metrics (job submissions, rejections, failures, latencies)
- Health check endpoint (`/healthz`)
- *Job-level log aggregation (e.g., streaming pod logs) is deferred — see below*
- Metrics are NOT labeled per-tenant in v1
- Tenant-specific debugging happens via logs or request tracing (if any)

### Resource Isolation
- Kubernetes resource requests/limits map to Linux cgroup enforcement
- Jobs run in a dedicated namespace (or namespaces) to isolate from system workloads

---

## Non-Functional Requirements

- **Latency:** Job submission API should respond in < 500ms (validation + K8s Job creation)
- **Availability:** Single-replica control plane is acceptable for v1 (no HA)
- **State:** In-memory only; losing the process loses job-tracking state (K8s remains source of truth for running jobs)
- **Deployment:** Control plane runs as a K8s Deployment; infra provisioned via Terraform
- **Scheduling**: No fairness, priority, or SLA guarantees; scheduling is delegated entirely to Kubernetes

---

## Hard Constraints

These are non-negotiable for v1:

- Single-region, single-cluster (AWS EKS)
- No authentication or identity system
- No persistent database (in-memory state only)
- No asynchronous job queue
- Kubernetes-native primitives over custom orchestration
- All secrets via environment variables; none committed to the repo
- Production-inspired design, not production-hardened

---

## Scope Boundaries

### In scope (v1)
- REST API for job CRUD (with optional GPU requests)
- API-layer admission control with configurable limits (CPU, memory, GPU, timeout)
- Per-tenant rate limiting (simple identifier, no auth)
- Per-tenant GPU quota enforcement (in-memory)
- Cost estimation (configurable CPU, memory, and GPU rates)
- K8s Job creation with resource limits, GPU requests, and timeout
- Retry via K8s `backoffLimit`
- Prometheus metrics and structured logging
- Terraform for EKS cluster provisioning
- Basic health checks

### Deferred (not v1)
- Authentication / RBAC
- Multi-cluster or multi-region
- Long-running services (batch-only)
- Database-backed persistence or job history
- Async job queues or priority scheduling
- Kubernetes admission webhooks
- Auto-scaling (cluster or control plane)
- Pod log streaming / aggregation from control plane
- Real AWS cost integration (Cost Explorer, CUR)
- CI/CD pipeline
- Advanced quota management (persistent, cross-resource budgets)

---

## Assumptions

- An EKS cluster exists (provisioned via Terraform in `infra/terraform/`)
- Nodes run Linux with cgroups v2
- The `kubernetes` Python client can authenticate to the cluster via in-cluster config or kubeconfig
- A single K8s namespace is sufficient for job isolation in v1
- Job container images are assumed trusted (no image policy enforcement in v1)
- GPU nodes with the NVIDIA device plugin are assumed available (but not required for v1 development)

---

## Open Questions

1. **Tenant identifier format** — Header (`X-Tenant-ID`) vs. request body field? Does it need validation against a known tenant list, or is it free-form?
2. **Default resource limits** — What are sensible defaults for max CPU, memory, and timeout per job? (e.g., 4 CPU / 8Gi / 1h)
3. **Job namespace strategy** — Single shared namespace for all jobs, or one namespace per tenant?
4. **Cost rate configuration** — Hardcoded defaults with env-var overrides, or a config file?

