"""
cost.py — Cost estimation preflight.

Computes the worst-case job cost before any Kubernetes resources are created.
Informational only — does not gate submission in v1.

We assume the job runs for its full timeout_s to surface worst-case spend,
especially for long GPU runs.

Rates are configurable via environment variables. Real AWS billing integration
is deferred (see docs/project_spec.md §Deferred).
"""

import os
from models import JobSpec

# Placeholder cost rates in USD per unit per second.
# These are not tied to real AWS billing in v1.
_CPU_RATE: float = float(os.getenv("COST_CPU_PER_CPU_SECOND", "0.000048"))
_MEMORY_RATE: float = float(os.getenv("COST_MEMORY_PER_GB_SECOND", "0.000006"))
_GPU_RATE: float = float(os.getenv("COST_GPU_PER_GPU_SECOND", "0.00028"))


def estimate_cost(spec: JobSpec) -> float:
    """
    Estimate the worst-case USD cost for a job if it runs for its full timeout.

      cpu_cost    = cpu_cores × timeout_s × CPU_RATE
      memory_cost = memory_gib × timeout_s × MEMORY_RATE
      gpu_cost    = gpu_count × timeout_s × GPU_RATE

    Returns total USD rounded to 6 decimal places.
    """
    # JobSpec uses memory_mb and K8s mapping uses Mi units, so treat this as GiB-ish.
    memory_gib = spec.memory_mb / 1024.0

    cpu_cost = spec.cpu * spec.timeout_s * _CPU_RATE
    memory_cost = memory_gib * spec.timeout_s * _MEMORY_RATE
    gpu_cost = spec.gpu_count * spec.timeout_s * _GPU_RATE

    return round(cpu_cost + memory_cost + gpu_cost, 6)