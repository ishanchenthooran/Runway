"""
k8s_client.py — Kubernetes Job creation and status queries.

This is the control-plane → data-plane boundary.
All Kubernetes I/O lives here.
"""

import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from models import JobSpec, JobStatusResponse, JobStatus

logger = logging.getLogger(__name__)

JOB_NAMESPACE: str = os.getenv("K8S_JOB_NAMESPACE", "runway-jobs")
BACKOFF_LIMIT: int = int(os.getenv("K8S_BACKOFF_LIMIT", "2"))


class KubernetesClient:
    def __init__(self) -> None:
        try:
            config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes config")
        except config.ConfigException:
            config.load_kube_config()
            logger.info("Loaded local kubeconfig")

        self._batch = client.BatchV1Api()
        self._core = client.CoreV1Api()

    # -------------------------------------------------------------
    # Job Submission
    # -------------------------------------------------------------

    def submit_job(self, spec: JobSpec) -> str:
        job_id = f"runway-{uuid.uuid4().hex[:8]}"

        # Base resources
        requests = {
            "cpu": str(spec.cpu),
            "memory": f"{spec.memory_mb}Mi",
        }

        limits = {
            "cpu": str(spec.cpu),
            "memory": f"{spec.memory_mb}Mi",
        }

        # GPU (must appear in BOTH requests and limits)
        if spec.gpu_count > 0:
            gpu_key = "nvidia.com/gpu"
            requests[gpu_key] = str(spec.gpu_count)
            limits[gpu_key] = str(spec.gpu_count)

        container = client.V1Container(
            name="job",
            image=spec.image,
            command=spec.command,
            args=spec.args,
            resources=client.V1ResourceRequirements(
                requests=requests,
                limits=limits,
            ),
        )

        pod_spec = client.V1PodSpec(
            restart_policy="Never",
            containers=[container],
        )

        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(
                labels={
                    "runway/tenant": spec.tenant_id,
                    "runway/job-id": job_id,
                }
            ),
            spec=pod_spec,
        )

        job_spec = client.V1JobSpec(
            backoff_limit=BACKOFF_LIMIT,
            active_deadline_seconds=spec.timeout_s,
            template=template,
        )

        job = client.V1Job(
            metadata=client.V1ObjectMeta(
                name=job_id,
                namespace=JOB_NAMESPACE,
            ),
            spec=job_spec,
        )

        self._batch.create_namespaced_job(
            namespace=JOB_NAMESPACE,
            body=job,
        )

        logger.info(
            "K8s Job created",
            extra={
                "job_id": job_id,
                "tenant_id": spec.tenant_id,
                "cpu": spec.cpu,
                "memory_mb": spec.memory_mb,
                "gpu_count": spec.gpu_count,
                "timeout_s": spec.timeout_s,
                "command": spec.command,
                "args": spec.args,
            },
        )

        return job_id

    # -------------------------------------------------------------
    # Status Queries
    # -------------------------------------------------------------

    def _get_pod_failure_reason(self, job_id: str) -> Optional[str]:
        """
        Look up the failure reason from the most recently terminated pod for a job.

        Why a separate pod query?
          The K8s Job object surfaces high-level state (Failed, Succeeded).
          Pod-level exit reasons (OOMKilled, NonZeroExit) live on the Pod object
          under container_statuses[].state.terminated. One extra API call is
          acceptable here — this only runs for terminal failed jobs.

        Pod selection:
          - Uses the runway/job-id label to find all pods for this job.
          - With backoffLimit > 0, multiple pods may exist (one per retry attempt).
          - We pick the most recently terminated pod (latest finished_at).
          - Within a pod, we prefer the container named "job" (our main container);
            if not found, we fall back to the first terminated container status.
        """
        try:
            pod_list = self._core.list_namespaced_pod(
                namespace=JOB_NAMESPACE,
                label_selector=f"runway/job-id={job_id}",
            )
        except ApiException:
            return None

        if not pod_list.items:
            return None

        # Collect (finished_at, terminated_state) for each pod.
        _epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)  # fallback for None timestamps
        candidates: list[tuple[datetime, object]] = []

        for pod in pod_list.items:
            if not pod.status or not pod.status.container_statuses:
                continue

            terminated = None

            # Prefer the main container by name ("job" is set in submit_job).
            for cs in pod.status.container_statuses:
                if cs.name == "job" and cs.state and cs.state.terminated:
                    terminated = cs.state.terminated
                    break

            # Fall back to the first terminated container status we find.
            if terminated is None:
                for cs in pod.status.container_statuses:
                    if cs.state and cs.state.terminated:
                        terminated = cs.state.terminated
                        break

            if terminated is not None:
                candidates.append((terminated.finished_at or _epoch, terminated))

        if not candidates:
            return None

        # Most recently terminated pod last seen = most relevant failure signal.
        candidates.sort(key=lambda x: x[0], reverse=True)
        _, most_recent = candidates[0]

        if most_recent.reason == "OOMKilled":
            return "OOMKilled"
        if most_recent.exit_code is not None and most_recent.exit_code != 0:
            return f"NonZeroExit (exit code {most_recent.exit_code})"
        return None

    def get_job_status(self, job_id: str) -> Optional[JobStatusResponse]:
        try:
            job = self._batch.read_namespaced_job(
                name=job_id,
                namespace=JOB_NAMESPACE,
            )
        except ApiException as e:
            if e.status == 404:
                return None
            raise

        status = job.status
        failure_reason: Optional[str] = None

        # Pending
        if not status.active and not status.succeeded and not status.failed:
            runway_status = JobStatus.PENDING

        # Running
        elif status.active:
            runway_status = JobStatus.RUNNING

        # Succeeded
        elif status.succeeded:
            runway_status = JobStatus.SUCCEEDED

        # Failed
        elif status.failed:
            # Check job conditions first — DeadlineExceeded is set here by K8s.
            deadline_exceeded = status.conditions and any(
                c.type == "Failed" and c.reason == "DeadlineExceeded"
                for c in status.conditions
            )

            if deadline_exceeded:
                runway_status = JobStatus.DEADLINE
                failure_reason = "DeadlineExceeded"
            else:
                runway_status = JobStatus.FAILED
                # Pod-level lookup: OOMKilled or NonZeroExit.
                failure_reason = self._get_pod_failure_reason(job_id)

        else:
            runway_status = JobStatus.PENDING

        tenant_id = job.metadata.labels.get("runway/tenant", "unknown")

        return JobStatusResponse(
            job_id=job_id,
            status=runway_status,
            tenant_id=tenant_id,
            failure_reason=failure_reason,
        )