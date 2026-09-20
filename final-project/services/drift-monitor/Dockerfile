# Image of the drift job.
#
# The build context is final-project/, because the image ships the reference
# sample the live data is compared with.
#
#   cd final-project
#   docker build -f services/drift-monitor/Dockerfile -t final-project/drift-monitor:local .

FROM ghcr.io/astral-sh/uv:0.8.3 AS uv

FROM python:3.13-slim AS builder

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY services/drift-monitor/pyproject.toml services/drift-monitor/uv.lock ./
RUN uv sync --locked --no-dev


FROM python:3.13-slim

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    # Evidently sends usage statistics home unless this is set. The package
    # also sets it itself, but a job in a private cluster should not depend on
    # one line of Python for that.
    DO_NOT_TRACK=1 \
    # Some libraries write caches into the home folder, which the user does
    # not have. /tmp is writable in every environment.
    HOME=/tmp \
    TMPDIR=/tmp

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY services/drift-monitor/drift_monitor ./drift_monitor
COPY data/reference.csv ./data/reference.csv

USER 10001:10001

ENTRYPOINT ["python", "-m", "drift_monitor"]
