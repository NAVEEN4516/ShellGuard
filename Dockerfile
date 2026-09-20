# ShellGuard Production Live Demo Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install essential dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and assets
COPY daemon/ ./daemon/
COPY data/ ./data/
COPY dashboard/out/ ./dashboard/out/
COPY web/ ./web/
COPY hooks/ ./hooks/
COPY cli.py .
COPY ARCHITECTURE.md .
COPY PRD.md .
COPY architecture_graph.json .

# Configure demo environment
ENV PYTHONUNBUFFERED=1
ENV SHELLGUARD_HOST=0.0.0.0
ENV SHELLGUARD_PORT=8080
ENV SHELLGUARD_DISABLE_AUTH=1
ENV SHELLGUARD_FAIL_POLICY=fail_open

EXPOSE 8080

# Launch daemon
CMD ["sh", "-c", "uvicorn daemon.server:app --host 0.0.0.0 --port ${PORT:-8080}"]
