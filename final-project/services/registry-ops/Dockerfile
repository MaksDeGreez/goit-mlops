# Image of the registry tool.
#
# It runs as a Kubernetes Job, started by an Argo CD PreSync hook. The build
# context is final-project/, the same as for the other services.
#
#   cd final-project
#   docker build -f services/registry-ops/Dockerfile -t final-project/registry-ops:local .

FROM ghcr.io/astral-sh/uv:0.8.3 AS uv

FROM python:3.13-slim AS builder

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY services/registry-ops/pyproject.toml services/registry-ops/uv.lock ./
RUN uv sync --locked --no-dev


FROM python:3.13-slim

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY services/registry-ops/registry_ops ./registry_ops

USER 10001:10001

# The command is the argument: "docker run <image> promote --version 3".
ENTRYPOINT ["python", "-m", "registry_ops"]
