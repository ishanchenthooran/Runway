"""
k8s_client.py — Kubernetes Job creation and status queries.

This is the control-plane → data-plane boundary.
All Kubernetes I/O lives here.
"""

import os
import uuid
import logging
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
            },
        )

        return job_id

    # -------------------------------------------------------------
    # Status Queries
    # -------------------------------------------------------------

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
            # Detect deadline exceeded
            if status.conditions:
                for condition in status.conditions:
                    if (
                        condition.type == "Failed"
                        and condition.reason == "DeadlineExceeded"
                    ):
                        runway_status = JobStatus.DEADLINE
                        break
                else:
                    runway_status = JobStatus.FAILED
            else:
                runway_status = JobStatus.FAILED
        else:
            runway_status = JobStatus.PENDING

        tenant_id = job.metadata.labels.get("runway/tenant", "unknown")

        return JobStatusResponse(
            job_id=job_id,
            status=runway_status,
            tenant_id=tenant_id,
        )