# examples/adept_asopb/Dockerfile — ASOPB evaluation framework
#
# Lightweight image for running the ASOPB evaluator, domain scoring, and tests.
# Does NOT include ML models, TruffleHog, Trivy, or Promptfoo (those are in the
# release scanner image at scripts/release/Dockerfile).
#
# Build:
#   docker build -t asopb:latest .
#
# Run evaluator:
#   docker run --rm -v $(pwd)/target_repo:/repo:ro asopb:latest asopb eval /repo
#
# Run tests:
#   docker run --rm asopb:latest pytest tests/ -v --tb=short

FROM python:3.11-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

RUN pip install --no-cache-dir -e ".[all]"

COPY tests/ ./tests/

RUN useradd --create-home --uid 1200 appuser
USER appuser

ENTRYPOINT ["python", "-m"]
CMD ["asopb.cli", "--help"]
