# Image of the training job.
#
# The build context is final-project/, because the image ships the dataset
# snapshot: nothing is downloaded at run time.
#
#   cd final-project
#   docker build -f services/training/Dockerfile -t final-project/training:local .

FROM ghcr.io/astral-sh/uv:0.8.3 AS uv

FROM python:3.13-slim AS builder

COPY --from=uv /uv /usr/local/bin/uv

# Compile the bytecode once at build time instead of on every start, copy the
# files instead of linking them (the cache is on another filesystem) and never
# download another Python: the base image already has 3.13.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Only the two files that describe the dependencies, so this layer is reused
# as long as they do not change.
COPY services/training/pyproject.toml services/training/uv.lock ./
RUN uv sync --locked --no-dev


FROM python:3.13-slim

# A fixed numeric id: Kubernetes checks runAsNonRoot against the number, not
# against the name.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# The files stay owned by root and are only readable, so the job cannot change
# its own code or the data it is measured on.
COPY --from=builder /app/.venv /app/.venv
COPY services/training/training ./training
COPY data/california_housing.csv ./data/california_housing.csv

USER 10001:10001

# There is no git in the image, so GIT_SHA has to be passed in. Everything
# else has a default; see services/training/README.md.
ENTRYPOINT ["python", "-m", "training.run"]
