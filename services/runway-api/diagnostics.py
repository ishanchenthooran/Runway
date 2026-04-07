"""
diagnostics.py — AI-backed job diagnostics agent.

## What this does

GET /jobs/{id}/diagnose invokes this agent. It runs a tool-use loop backed
by the Claude API to investigate why a job failed and suggest a fix.

## Agentic loop

The agent has two tools:

  get_job_status(job_id)  — returns current status and failure_reason from K8s
  get_job_spec(job_id)    — returns the original resource requests (cpu, memory_mb,
                            gpu_count, timeout_s, image) stored at submission time

Claude calls these tools to gather evidence, then produces a natural-language
diagnosis with a concrete remediation suggestion.

## Why tool use and not a simple prompt?

A plain prompt with the job info pasted in would work, but tool use demonstrates
the agent's ability to decide what to look at — it mirrors how a real on-call
engineer would query systems rather than being handed a pre-packaged summary.
For a two-tool demo this is a meaningful architectural distinction.

## Design constraints

- Stateless: no conversation history stored between calls
- Synchronous: the route blocks while the agent loop runs (acceptable for demo)
- Fails loudly: any API or tool error surfaces as an HTTP 500 with a clear message
"""

import json
import logging
import os

import anthropic

from models import JobSpec, JobStatusResponse

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"  # Fast and cheap — diagnostics don't need Opus

SYSTEM_PROMPT = """\
You are a Kubernetes batch job diagnostics agent for the Runway platform.

Runway is an internal control plane that runs batch jobs on Kubernetes. Jobs can
fail for infrastructure reasons: OOMKilled (container exceeded its memory limit),
DeadlineExceeded (job ran past its timeout), or NonZeroExit (process crashed).

Your job:
1. Use the available tools to gather information about the failed job.
2. Identify the root cause of the failure.
3. Provide a clear, concrete remediation — e.g. "Increase memory_mb from 32 to at
   least 256" or "Increase timeout_s from 5 to at least 60".

Be specific and actionable. Do not hedge excessively. If you cannot determine
a root cause from the available information, say so plainly.
"""

TOOLS: list[dict] = [
    {
        "name": "get_job_status",
        "description": (
            "Fetch the current status of a Runway job from Kubernetes. "
            "Returns the job's status (PENDING, RUNNING, SUCCEEDED, FAILED, DEADLINE) "
            "and, if the job failed, the failure_reason (OOMKilled, DeadlineExceeded, "
            "NonZeroExit, or similar)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "The Runway job ID (e.g. 'runway-abc12345')",
                }
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "get_job_spec",
        "description": (
            "Fetch the original resource specification that was submitted for a job. "
            "Returns image, cpu (cores), memory_mb, gpu_count, and timeout_s. "
            "Use this to understand what resources were requested when diagnosing "
            "resource-related failures like OOMKilled or DeadlineExceeded."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "The Runway job ID (e.g. 'runway-abc12345')",
                }
            },
            "required": ["job_id"],
        },
    },
]


class DiagnosticsAgent:
    """
    Runs a tool-use loop against the Claude API to diagnose a failed job.

    Constructed once at application startup (alongside other singletons in main.py).
    The job_specs dict is populated by main.py on every successful submission so
    get_job_spec() has data to return.
    """

    def __init__(
        self,
        k8s,  # KubernetesClient — injected to avoid circular import
        job_specs: dict[str, JobSpec],
    ) -> None:
        self._k8s = k8s
        self._job_specs = job_specs
        self._client = anthropic.Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"]
        )

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def diagnose(self, job_id: str) -> str:
        """
        Run the agentic loop for the given job and return a diagnosis string.

        Raises ValueError if ANTHROPIC_API_KEY is not set.
        Raises anthropic.APIError on API-level failures.
        """
        logger.info("Diagnostics agent: starting", extra={"job_id": job_id})

        messages = [
            {
                "role": "user",
                "content": (
                    f"Please diagnose job '{job_id}'. "
                    "Investigate what happened and suggest a concrete fix."
                ),
            }
        ]

        # Agentic loop: keep going until Claude stops calling tools.
        while True:
            response = self._client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

            logger.debug(
                "Diagnostics agent: Claude response",
                extra={"stop_reason": response.stop_reason, "job_id": job_id},
            )

            # Append Claude's response to the conversation.
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                # Claude is done — extract the final text block.
                for block in response.content:
                    if hasattr(block, "text"):
                        logger.info(
                            "Diagnostics agent: complete", extra={"job_id": job_id}
                        )
                        return block.text
                return "Diagnosis complete (no text output produced)."

            if response.stop_reason == "tool_use":
                # Execute all tool calls Claude requested, then continue the loop.
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = self._execute_tool(block.name, block.input)
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(result),
                            }
                        )
                messages.append({"role": "user", "content": tool_results})
                continue

            # Unexpected stop reason — surface it clearly.
            raise RuntimeError(
                f"Diagnostics agent: unexpected stop_reason '{response.stop_reason}'"
            )

    # ------------------------------------------------------------------
    # Internal: tool execution
    # ------------------------------------------------------------------

    def _execute_tool(self, name: str, inputs: dict) -> dict:
        """Dispatch a tool call and return a JSON-serialisable result dict."""
        job_id = inputs["job_id"]

        if name == "get_job_status":
            return self._tool_get_job_status(job_id)
        if name == "get_job_spec":
            return self._tool_get_job_spec(job_id)

        return {"error": f"Unknown tool '{name}'"}

    def _tool_get_job_status(self, job_id: str) -> dict:
        logger.info(
            "Diagnostics agent: tool call get_job_status",
            extra={"job_id": job_id},
        )
        status_response: JobStatusResponse | None = self._k8s.get_job_status(job_id)
        if status_response is None:
            return {"error": f"Job '{job_id}' not found in Kubernetes"}
        return {
            "job_id": job_id,
            "status": status_response.status.value,
            "failure_reason": status_response.failure_reason,
        }

    def _tool_get_job_spec(self, job_id: str) -> dict:
        logger.info(
            "Diagnostics agent: tool call get_job_spec",
            extra={"job_id": job_id},
        )
        spec: JobSpec | None = self._job_specs.get(job_id)
        if spec is None:
            return {
                "error": (
                    f"Spec for job '{job_id}' not found. "
                    "It may have been submitted before this process started."
                )
            }
        return {
            "job_id": job_id,
            "image": spec.image,
            "cpu": spec.cpu,
            "memory_mb": spec.memory_mb,
            "gpu_count": spec.gpu_count,
            "timeout_s": spec.timeout_s,
        }
