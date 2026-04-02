# Project Status — Runway

_Last updated: 2026-04-02_

---

## Project Phase

v0.9.0 complete. All original milestones done. Phase 5 in progress: AI Diagnostics Agent — agentic `GET /jobs/{id}/diagnose` endpoint backed by Claude API tool use.

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
- [x] Rate limiting implemented (fixed-window, per-tenant, `rate_limit.py`)
- [x] Job failure reason surfaced in status response (OOMKilled, DeadlineExceeded, NonZeroExit)
- [x] GPU quota released on job completion (background reconciler, polling)
- [x] EKS cluster provisioned via Terraform (VPC, managed node group, ca-central-1)
- [x] Control plane deployed to EKS (Dockerfile + K8s Deployment + Service)
- [x] Observability stack deployed (Prometheus scraping, Grafana)
- [x] End-to-end smoke test passed (job submission → K8s Job created → status polled successfully)
- [x] Demo-ready build (end-to-end submission flow, failure surfaces, cost output)
- [x] Grafana dashboard created (submission rate, rejections by reason, p50/p99 latency, failures by reason)
- [x] All 4 demo scenarios validated end-to-end on kind (happy path, OOMKilled, GPU quota rejection, rate limit)
- [x] Scale analysis written (`docs/scale_analysis.md`)
- [x] Demo script written (`docs/demo_script.md`)
- [ ] **Phase 5: AI Diagnostics Agent** — `GET /jobs/{id}/diagnose` using Claude API tool use
  - [ ] `services/runway-api/diagnostics.py` — agent loop, tool definitions, agentic loop
  - [ ] Route wired into `main.py`
  - [ ] `runway_diagnoses_total` Prometheus metric
  - [ ] Demo scenario E: OOMKilled → diagnose → remediated resubmit

---

## Functional Gaps (blocking demo)

These are not polish — they affect correctness or completeness of the core flow.

### ~~1. Rate limiting not implemented~~ ✓ Resolved
- `rate_limit.py` implemented: fixed-window, per-tenant, thread-safe.
- `RATE_LIMITED` metric label now emits correctly via existing HTTPException handler.
- 429 response includes `Retry-After` header and `retry_after_s` body field.

### ~~2. `failure_reason` never populated~~ ✓ Resolved
- `_get_pod_failure_reason()` added to `k8s_client.py`.
- Lists pods by `runway/job-id` label, picks most recently terminated pod.
- Prefers container named `"job"`; falls back to first terminated container status.
- Surfaces `OOMKilled`, `NonZeroExit (exit code N)`, and `DeadlineExceeded`.

### ~~3. GPU quota never released on job completion~~ ✓ Resolved
- `QuotaReconciler` added (`quota_reconciler.py`): background async task, polls K8s every 30s.
- On terminal state (SUCCEEDED, FAILED, DEADLINE): calls `quota.release()` and removes job from tracker.
- Registered via FastAPI `lifespan`; started/stopped cleanly with the process.
- `asyncio.to_thread()` used for blocking K8s calls; `asyncio.Lock` guards `_active_jobs` on the async path.

### ~~4. No `command` field on `JobSpec`~~ ✓ Resolved
- `command: Optional[list[str]]` and `args: Optional[list[str]]` added to `JobSpec`.
- `command` overrides Docker `ENTRYPOINT` (maps to `container.command`); `args` overrides Docker `CMD` (maps to `container.args`).
- Both are optional; omitting either preserves the image default.

---

## Known Limitations (by design for v1)

- **Single replica** — control plane has no HA; a crash interrupts submission until restart
- **In-memory state** — GPU quota counters are lost on restart; no reconciliation on startup in v1
- **No authentication** — tenant identity is caller-supplied and unverified
- **No persistent quotas** — quota state cannot survive process restarts or be shared across replicas
- **No pod log streaming** — job-level logs require direct `kubectl logs` access
- **No real cost integration** — estimates use static rates; not tied to AWS billing
