# Project Status — Runway

_Last updated: 2026-02-19_

---

## Project Phase

Documentation complete. Control plane not yet implemented.

---

## Milestones

- [x] Project specification defined (`docs/project_spec.md`)
- [x] Architecture defined (`docs/architecture.md`)
- [x] AI-infra pivot — GPU quota enforcement and cost guardrails scoped
- [ ] FastAPI control plane scaffold (routes, config, health check)
- [ ] Kubernetes Job creation working (validated spec → `batch/v1 Job`)
- [ ] GPU quota enforcement (in-memory counter, admission rejection)
- [ ] Cost estimation implemented (preflight, env-var rates, response field)
- [ ] Observability stack deployed (Prometheus metrics, structured logs)
- [ ] Demo-ready build (end-to-end submission flow, failure surfaces, cost output)

---

## Next 2 Weeks Focus

- Scaffold FastAPI app with `/jobs`, `/jobs/{id}`, and `/healthz` endpoints
- Implement admission control: per-job bounds, GPU max, per-tenant quota
- Wire Kubernetes Python client for Job creation and status queries
- Implement cost estimation preflight with configurable rates
- Add structured logging and Prometheus `/metrics` endpoint
- Validate end-to-end flow against a local or test cluster

---

## Known Limitations

- **Single replica** — control plane has no HA; a crash interrupts submission until restart
- **In-memory state** — GPU quota counters and rate limit windows are lost on restart; no reconciliation on startup in v1
- **No authentication** — tenant identity is caller-supplied and unverified
- **No persistent quotas** — quota state cannot survive process restarts or be shared across replicas
- **No pod log streaming** — job-level logs require direct `kubectl logs` access
- **No real cost integration** — estimates use static rates; not tied to AWS billing
