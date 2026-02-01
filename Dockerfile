FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (cached layer)
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --no-dev --frozen --no-install-project

# Copy application code
COPY pinchwork/ pinchwork/
COPY migrations/ migrations/
COPY skill.md .
COPY pinchwork-cli/install.sh pinchwork-cli/install.sh

# Install the project itself
RUN uv sync --no-dev --frozen

RUN mkdir -p /app/data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

CMD ["uv", "run", "uvicorn", "pinchwork.main:app", "--host", "0.0.0.0", "--port", "8000"]
