# Build stage: install dependencies
FROM python:3.12-slim AS build

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency specs and source for package installation
COPY pyproject.toml uv.lock* ./
COPY src/ ./src/

# Install dependencies and the package itself
RUN uv pip install --system .

# Runtime stage: minimal image with installed packages
FROM python:3.12-slim AS runtime

WORKDIR /app

# Copy installed packages from build stage
COPY --from=build /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=build /usr/local/bin /usr/local/bin

# Pre-install common skill dependencies
# These are available to all skills without additional installs.
RUN pip install --no-cache-dir \
    aiohttp \
    beautifulsoup4 \
    httpx \
    lxml

# Copy data directories (not Python packages)
COPY personalities/ ./personalities/
COPY skills/ ./skills/

# Create non-root app user and logs directory for agent round-trip logging
RUN useradd -m appuser && mkdir -p /app/logs && chown -R appuser:appuser /app

# Health check: verify the agent is responding
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')" || exit 1

# Switch to non-root user
USER appuser

# Run the agent
CMD python -m pillywiggins --agent-id "${AGENT_ID}"