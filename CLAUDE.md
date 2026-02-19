# CLAUDE.md — Runway

This file defines how Claude should collaborate on the Runway codebase.
Claude must follow these rules before proposing designs, code, or changes.

Failure to follow these rules is considered incorrect behavior.

---

## 1. Project Overview

**Runway** is an internal, AI-infrastructure-aware batch job execution platform
built on Kubernetes (AWS EKS).

It enables internal teams to submit batch jobs — including GPU-backed ML training workloads —
safely while enforcing:
- resource isolation (CPU, memory, GPU)
- admission control, GPU quota enforcement, and rate limiting
- failure recovery
- observability
- cost awareness (CPU, memory, and GPU pricing)

Runway is **not** a user-facing product or an ML platform.
It does not track models, experiments, or training artifacts.
It is an internal infrastructure control plane that protects shared clusters
from GPU starvation and runaway training costs.

---

## 2. Core Goals

Claude must optimize for the following goals, in priority order:

1. **Infrastructure safety over features**
2. **Clarity over cleverness**
3. **Explicit trade-offs over completeness**
4. **Production-inspired design, minimal implementation**
5. **Interview- and demo-ready artifacts**

If a design increases complexity without clear infra value, it should be rejected.

---

## 3. Architecture (High-Level)

Runway follows a **control plane / data plane** separation:

- **Control Plane**
  - Python (FastAPI) service
  - Validates job submissions
  - Enforces admission control and rate limiting
  - Submits Kubernetes Jobs
  - Exposes metrics and logs
  - Performs cost estimation (CPU, memory, GPU)
  - Enforces GPU quota per tenant

- **Data Plane**
  - Kubernetes Jobs and Pods
  - Linux-enforced resource limits (cgroups) and GPU scheduling via NVIDIA device plugin
  - Retry and failure handling via Kubernetes semantics

Claude must preserve this separation.

Detailed diagrams and rationale live in:
- `docs/architecture.md`

---

## 4. Engineering Principles

Claude must adhere to these principles:

- Prefer **simple, explicit designs**
- Fail fast and loudly
- Make Linux behavior visible (OOMKilled, SIGTERM, throttling)
- Favor stateless components where possible
- Assume infrastructure is hostile and must be protected
- Treat cost as a first-class concern
- Design for observability, not post-hoc debugging

---

## 5. Hard Constraints (Non-Negotiable)

Claude must never violate these constraints:

- This is a **single-region, single-cluster** system
- No authentication or identity system in v1
- No database in v1 (in-memory state is acceptable)
- No asynchronous queues in v1
- No model/ML-level abstractions (no experiment tracking, model registries, fine-tuning, distributed training)
- Kubernetes-native primitives preferred over custom orchestration
- Simplicity is favored over scalability beyond demo scope
- All secrets must use environment variables
- No secrets may be committed to the repository
- `docs/project_spec.md` is the canonical source of truth — Claude must check it before proposing new features

---

## 6. Admission Control & Safety Policy

Runway must protect:
- the API
- the Kubernetes cluster
- cluster nodes
- other tenants

Claude must:
- validate all job specs before submission
- enforce strict CPU, memory, GPU, and timeout bounds
- enforce per-tenant GPU quota (in-memory)
- implement rate limiting per tenant
- reject unsafe or abusive requests explicitly

Claude should prefer **API-layer admission control**
and explain why Kubernetes admission webhooks are out of scope for v1.

---

## 7. Repository Etiquette & Git Workflow

Claude must follow these repository rules:

### Branching
- Never push directly to `main`
- All changes must go through a feature branch
- Branch naming:
  - `feat/<short-description>`
  - `fix/<short-description>`
  - `docs/<short-description>`
  - `infra/<short-description>`

### Pull Requests
- Claude should assume all non-trivial changes go through PRs
- PRs should include:
  - clear summary
  - motivation
  - trade-offs
  - what was intentionally left out

Claude should ask:
> “Should this be a PR or a local change?”

before proposing multi-file changes.

---

## 8. Documentation Policy (Very Important)

Runway uses **automated, living documentation** to maintain project context.

Claude is expected to:
- read relevant docs before proposing changes
- keep docs up to date when behavior or design changes
- suggest doc updates explicitly when appropriate

### Core Documentation Files

Claude should reference (and update when needed):

- `docs/project_spec.md`
  - canonical project requirements and scope

- `docs/architecture.md`
  - architecture diagrams
  - control plane / data plane explanation
  - key design decisions

- `docs/features.md`
  - high-level overview of core features
  - admission control
  - rate limiting
  - observability
  - cost estimation

- `docs/project_status.md`
  - milestones
  - what is complete
  - what is in progress
  - what is next

- `docs/changelog.md`
  - notable design and behavior changes
  - versioned updates

Claude should **not duplicate this content** inside CLAUDE.md.
Instead, it should link to or update the relevant document.

---

## 9. Frequently Used Commands

Claude may reference these commands when suggesting workflows.

### Local development
```bash
# Run Runway API
uvicorn main:app --reload

# Activate virtualenv
source .venv/bin/activate


Claude may reference the following commands when suggesting workflows or debugging steps. 

### Kubernetes
kubectl get pods -A
kubectl describe pod <pod>
kubectl logs <pod>

### Terraform
terraform init
terraform plan
terraform apply

### Observability
kubectl port-forward svc/grafana 3000:80
