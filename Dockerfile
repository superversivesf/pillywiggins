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

# Copy data directories (not Python packages)
COPY personalities/ ./personalities/
COPY skills/ ./skills/

# Run the agent
CMD ["python", "-m", "pillywiggins", "--channel", "telegram"]