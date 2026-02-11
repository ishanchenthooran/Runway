# Project Specification — Runway

> This is the canonical source of truth for Runway's requirements and scope.
> Other docs may summarize, but this file is authoritative.

---

## Problem Statement

Internal engineering teams need to run batch workloads on shared Kubernetes infrastructure. Without guardrails, individual jobs
can starve cluster resources, fail silently, or run indefinitely with no cost visibility.

Runway provides a thin control plane that accepts, validates, and submits batch jobs
to Kubernetes while enforcing resource limits, rate limiting, and basic cost awareness.

---

## Target Users

- Internal engineering teams submitting batch workloads
- Platform operators monitoring cluster health and job outcomes
- No external or end-user access

---

## Functional Requirements (v1)

### Job Submission
- Accept job specs via REST API (container image, resource requests, timeout)
- Validate specs against admission policy before creating K8s resources
- Return a job identifier on successful submission
- Support job status queries and listing
- Job status reflects Kubernetes Job/Pod state; Runway does not maintain an independent scheduler or state machine

### Admission Control
- Enforce per-job bounds on CPU, memory, and wall-clock timeout
- Reject jobs that exceed configured limits with clear error messages
- All validation happens at the API layer (no K8s admission webhooks in v1)

### Rate Limiting
- Enforce per-tenant submission rate limits
- *Assumption: tenants are identified by a simple identifier passed in the request
  (e.g., a header or field) — no authentication system backs this in v1*

### Cost Estimation
- Estimate job cost before submission based on requested resources and timeout
- Surface cost estimate in the API response
- *Assumption: cost model uses a configurable $/cpu-second and $/GB-second rate —
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
- REST API for job CRUD
- API-layer admission control with configurable limits
- Per-tenant rate limiting (simple identifier, no auth)
- Cost estimation (configurable resource rates)
- K8s Job creation with resource limits and timeout
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
- Quota management (per-tenant resource budgets)

---

## Assumptions

- An EKS cluster exists (provisioned via Terraform in `infra/terraform/`)
- Nodes run Linux with cgroups v2
- The `kubernetes` Python client can authenticate to the cluster via in-cluster config or kubeconfig
- A single K8s namespace is sufficient for job isolation in v1
- Job container images are assumed trusted (no image policy enforcement in v1)

---

## Open Questions

1. **Tenant identifier format** — Header (`X-Tenant-ID`) vs. request body field? Does it need validation against a known tenant list, or is it free-form?
2. **Default resource limits** — What are sensible defaults for max CPU, memory, and timeout per job? (e.g., 4 CPU / 8Gi / 1h)
3. **Job namespace strategy** — Single shared namespace for all jobs, or one namespace per tenant?
4. **Cost rate configuration** — Hardcoded defaults with env-var overrides, or a config file?

