# Image of the prediction API.
#
# The build context is final-project/, the same as for the other services, so
# one .dockerignore covers all of them.
#
#   cd final-project
#   docker build -f services/inference/Dockerfile -t final-project/inference:local .

FROM ghcr.io/astral-sh/uv:0.8.3 AS uv

FROM python:3.13-slim AS builder

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY services/inference/pyproject.toml services/inference/uv.lock ./
RUN uv sync --locked --no-dev


FROM python:3.13-slim

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    # The downloaded model goes into a temporary folder. Naming it here means
    # /tmp is the only place the container has to be able to write, so it can
    # run with a read-only root filesystem and a small tmpfs on /tmp.
    TMPDIR=/tmp \
    # One row at a time is far too little work to share between threads. With
    # the default number of OpenMP threads a prediction took 68 ms in the
    # container and 3.3 ms with one thread: the whole time went into starting
    # and synchronising threads. A pod also gets a small CPU limit, so one
    # thread is the honest setting anyway.
    OMP_NUM_THREADS=1

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY services/inference/inference ./inference

USER 10001:10001

EXPOSE 8000

# A plain Python request, so the image needs no curl or wget. It uses the
# default port; a container started with another PORT should switch the
# healthcheck off or override it.
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"]

# Starts uvicorn on 0.0.0.0:8000 with its access log switched off: the service
# writes one JSON line per request itself. See services/inference/README.md.
CMD ["python", "-m", "inference"]
