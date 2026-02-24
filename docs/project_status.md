# Project Status — Runway

_Last updated: 2026-02-22_

---

## Project Phase

Control plane implemented. Functional gaps remain before demo-ready.

---

## Milestones

- [x] Project specification defined (`docs/project_spec.md`)
- [x] Architecture defined (`docs/architecture.md`)
- [x] AI-infra pivot — GPU quota enforcement and cost guardrails scoped
- [x] FastAPI control plane scaffold (routes, config, health check)
- [x] Kubernetes Job creation working (validated spec → `batch/v1 Job`)
- [x] GPU quota enforcement (in-memory counter, admission rejection)
- [x] Cost estimation implemented (preflight, env-var rates, response field)
- [x] Observability scaffolded (Prometheus metrics defined, structured logging in place)
- [ ] Rate limiting implemented (module referenced but not yet written)
- [ ] Job failure reason surfaced in status response
- [ ] GPU quota released on job completion
- [ ] Observability stack deployed (Prometheus scraping, Grafana)
- [ ] Demo-ready build (end-to-end submission flow, failure surfaces, cost output)

---

## Functional Gaps (blocking demo)

These are not polish — they affect correctness or completeness of the core flow.

### 1. Rate limiting not implemented
- `admission.py` and `metrics.py` reference rate limiting, but no `rate_limit.py` exists.
- A `RATE_LIMITED` rejection reason is referenced in metrics but never emitted.
- **Impact:** per-tenant rate limiting is entirely absent.

### 2. `failure_reason` never populated
- `JobStatusResponse` has a `failure_reason: Optional[str]` field.
- `k8s_client.get_job_status()` detects `FAILED` and `DEADLINE` states but never sets `failure_reason`.
- Kubernetes surfaces OOMKilled, NonZeroExit, and DeadlineExceeded on pod conditions — none of this is passed back to the caller.
- **Impact:** users have no signal for why their job failed.

### 3. GPU quota never released on job completion
- `quota.release()` is called correctly on K8s submission failure (rollback path).
- It is never called when a job finishes or fails in Kubernetes.
- There is no polling loop or reconciliation mechanism in v1.
- **Impact:** GPU quota slowly drains to zero and never recovers without a process restart.

### 4. No `command` field on `JobSpec`
- Pods will execute the container image's default `CMD`.
- Acceptable for demo if images have sensible defaults, but limits flexibility.
- **Impact:** low — callers cannot specify what the container runs.

---

## Known Limitations (by design for v1)

- **Single replica** — control plane has no HA; a crash interrupts submission until restart
- **In-memory state** — GPU quota counters are lost on restart; no reconciliation on startup in v1
- **No authentication** — tenant identity is caller-supplied and unverified
- **No persistent quotas** — quota state cannot survive process restarts or be shared across replicas
- **No pod log streaming** — job-level logs require direct `kubectl logs` access
- **No real cost integration** — estimates use static rates; not tied to AWS billing
