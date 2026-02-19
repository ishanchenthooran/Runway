# Changelog

All notable changes to Runway are documented here.

---

## [Unreleased]

- AI-infrastructure pivot: GPU quota enforcement and cost estimation added as core features
- Project specification defined (`docs/project_spec.md`)
- Architecture document created (`docs/architecture.md`)
- Features overview documented (`docs/features.md`)
- Project status tracking established (`docs/project_status.md`)
- Documentation structure scaffolded across `docs/`

---

## [0.1.0] — 2026-02-19

### Added
- Initial project commit
- README with project overview
- Documentation scaffold: `project_spec.md`, `architecture.md`, `features.md`, `project_status.md`, `changelog.md`
- Pivoted Runway scope to AI-infrastructure-aware control plane
  - GPU quota enforcement per tenant
  - Cost estimation for CPU, memory, and GPU workloads
  - Admission control for GPU-backed ML training jobs
- `CLAUDE.md` with engineering principles, hard constraints, and collaboration guidelines

---

*Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).*
