# Scale Analysis — Runway v1

_Last updated: 2026-04-01_

This document describes what breaks in Runway at 10× tenant load,
why each failure mode exists, and what a v2 design would change.
It is intentionally honest: v1 is designed for demo scope, not production scale.

---

## Baseline (v1 Design Point)

- Single replica FastAPI process
- In-memory GPU quota store (`quota.py`)
- In-memory rate limiter (`rate_limit.py`)
- Background quota reconciler polling K8s every 30s
- No database, no queue, no external state
- Prometheus metrics scraped at 15s intervals

---

## What Breaks at 10× Load

### 1. In-Memory Quota State — Lost on Restart

**What it is:** `GPUQuotaStore` is a plain Python dict with a threading lock.
All GPU allocations live in process memory.

**What breaks:** Any process restart (crash, OOM, rolling deploy) resets all quota
counters to zero. Active jobs continue running in Kubernetes, but Runway no longer
knows they are consuming quota. On restart, every tenant appears to have full quota —
a tenant that had 8/8 GPUs allocated can immediately submit 8 more.

**Scale amplifier:** At 10× tenants and job volume, restart frequency increases
(more deploys, more OOM risk from higher memory pressure on the control plane itself).
The window of ghost quota is proportionally more dangerous.

**v2 fix:** Replace `GPUQuotaStore` with a Redis-backed counter (`INCR`/`DECR`).
Redis survives process restarts. Multiple replicas share a single consistent view.
The quota reconciler becomes a convergence mechanism rather than the primary source
of truth.

---

### 2. In-Memory Rate Limiter — Not Shared Across Replicas

**What it is:** `RateLimiter` uses a per-process dict keyed on `tenant_id`.
Each replica counts independently.

**What breaks:** At scale, the control plane needs multiple replicas behind a
load balancer. Each replica has its own window counter. A tenant hitting 10 replicas
can submit `limit × replicas` requests per window — effectively defeating rate limiting.

**Scale amplifier:** Horizontal scaling is the natural response to increased load.
The current design gets *less safe* as you scale out.

**v2 fix:** Move rate limit state to Redis using a sliding window or fixed-window
counter keyed on `tenant_id`. All replicas share one counter. `INCR` + TTL is
the standard Redis pattern for this.

---

### 3. Quota Reconciler — 30-Second Poll Lag

**What it is:** `QuotaReconciler` polls Kubernetes every 30 seconds, checks terminal
job states, and releases quota.

**What breaks:** In a high-throughput scenario (many short jobs), quota is not released
for up to 30 seconds after a job completes. A tenant running many short GPU jobs will
hit their quota ceiling even though most jobs have already finished. Effective throughput
is throttled below the actual quota ceiling.

**Scale amplifier:** Short-duration jobs (< 30s) are penalized most severely.
GPU-intensive ML inference jobs or hyperparameter search jobs often fall in this range.

**v2 fix:** Use Kubernetes watch (`watch=True` on the Job API) instead of polling.
The reconciler receives push notifications on job state changes and releases quota
within seconds. Alternatively, a webhook from a K8s Job controller could trigger quota
release.

---

### 4. Metric Cardinality — Labels at Scale

**What it is:** Current metrics avoid per-tenant labels intentionally (`metrics.py`
comment: "avoid cardinality issues in v1").

**What breaks (if per-tenant labels were added):** At 10× tenants, each metric with
a `tenant_id` label generates 10× as many time series. Prometheus memory usage scales
linearly with series count. At hundreds of tenants, this becomes a storage and query
performance problem.

**What breaks (with current design):** Operators cannot distinguish which tenant is
generating the most rejections or failures — the dashboard shows aggregate counts only.

**Scale trade-off:** This is a deliberate v1 choice. The correct v2 approach is:
- Keep aggregate metrics without tenant labels in Prometheus
- Ship per-tenant events to a structured log aggregator (Loki, Elasticsearch)
- Build per-tenant views from log queries, not metric labels

---

### 5. Single Control Plane Replica — No HA

**What it is:** One pod. No `PodDisruptionBudget`, no `HorizontalPodAutoscaler`.

**What breaks:** Any crash, node eviction, or rolling deploy interrupts job submissions
for the duration of pod restart (typically 10–30s). In-memory state is lost.

**Scale amplifier:** Higher submission rate increases the cost of downtime.
At 10× load, a 30-second outage may mean hundreds of dropped submissions.

**v2 fix:**
- Run ≥ 2 replicas with a `PodDisruptionBudget`
- Externalize all state (Redis for quota/rate limits, Postgres for job history)
- The control plane becomes fully stateless — any replica can handle any request

---

## v2 Architecture Summary

| Component | v1 | v2 |
|---|---|---|
| GPU quota store | In-memory dict | Redis `INCR`/`DECR` per tenant |
| Rate limiter | In-memory dict | Redis fixed-window counter |
| Job history | None (K8s only) | Postgres jobs table |
| Quota reconciler | 30s poll | K8s watch (push) |
| Replicas | 1 | ≥ 2, behind load balancer |
| Metric granularity | Aggregate only | Aggregate in Prometheus + per-tenant in Loki |

The API contract and Kubernetes integration are unchanged. v2 is a state backend
swap, not a redesign.

---

## What Does Not Break at 10× Load

- **Admission control** (`admission.py`) — pure function, no state, scales linearly
- **Cost estimation** (`cost.py`) — pure math, no state
- **K8s Job creation** (`k8s_client.py`) — stateless API calls; K8s API server is the bottleneck, not Runway
- **Prometheus metrics emission** — negligible overhead per request
- **Structured logging** — I/O bound; scales with log aggregator capacity

These components require no changes for 10× load.
