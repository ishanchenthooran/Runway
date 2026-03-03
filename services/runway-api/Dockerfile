# ---------------------------------------------------------------------------
# Runway Control Plane — Container Image
#
# Build:  docker build -t runway-api services/runway-api/
# Run:    docker run -p 8000:8000 runway-api
#
# In production (EKS), the container uses in-cluster config for K8s auth.
# Locally, mount your kubeconfig: -v ~/.kube:/root/.kube
# ---------------------------------------------------------------------------

FROM python:3.11-slim

WORKDIR /app

# Install dependencies in a separate layer so Docker can cache them.
# Re-runs only when requirements.txt changes, not on every source edit.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source.
COPY . .

EXPOSE 8000

# --host 0.0.0.0: listen on all interfaces (required inside a container).
# --port 8000:    explicit; avoids relying on the default.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
