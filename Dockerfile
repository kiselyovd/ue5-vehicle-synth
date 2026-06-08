# syntax=docker/dockerfile:1.7
ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION}-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential curl git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.5.*
WORKDIR /app

FROM base AS training
COPY pyproject.toml uv.lock* README.md ./
RUN uv sync --frozen --group tracking
COPY . .
ENV PATH="/app/.venv/bin:${PATH}"
ENTRYPOINT ["python", "-m", "ue5_vehicle_synth.training.train"]

