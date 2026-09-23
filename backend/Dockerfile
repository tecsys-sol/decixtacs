# syntax=docker/dockerfile:1.7
# NetworkOps Manager - backend image (API, Celery workers, beat, migrations, bootstrap).
#
#   docker build -t networkops/backend ./backend
#   docker run --rm networkops/backend api        # uvicorn on :8000
#   docker run --rm networkops/backend worker     # celery worker (NOM_WORKER_QUEUES)
#   docker run --rm networkops/backend beat       # celery beat (run exactly one)
#   docker run --rm networkops/backend migrate    # alembic upgrade head
#   docker run --rm networkops/backend init       # first tenant + admin (NOM_INIT_*)

ARG PYTHON_IMAGE=python:3.12-slim-bookworm

# ---------------------------------------------------------------------------------------------
# Build stage: compile wheels (some collector deps need a compiler) into an isolated venv.
# ---------------------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libffi-dev libssl-dev \
 && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /src
# Dependency layer first (cached as long as pyproject.toml does not change).
COPY pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py \
 && pip install --upgrade pip setuptools wheel \
 && pip install ".[collectors]" \
 && pip uninstall -y networkops-manager
# Application code.
COPY app ./app
RUN pip install --no-deps ".[collectors]"

# ---------------------------------------------------------------------------------------------
# Runtime stage.
# ---------------------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime
ARG VERSION=dev
ARG VCS_REF=unknown
LABEL org.opencontainers.image.title="networkops-manager-backend" \
      org.opencontainers.image.description="NetworkOps Manager API / workers" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.source="https://github.com/tecsys-sol/decixtacs" \
      org.opencontainers.image.licenses="Proprietary"

# git: config repositories (GitPython shells out to git); openssh-client: Scrapli system transport
# / Netmiko key handling; tini: correct signal handling + zombie reaping for celery.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git openssh-client tini ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 nom \
 && useradd --system --uid 10001 --gid nom --home-dir /home/nom --create-home --shell /usr/sbin/nologin nom \
 && mkdir -p /var/lib/nom/configs /var/lib/nom/recordings /var/lib/nom/prometheus \
 && chown -R nom:nom /var/lib/nom

COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY --chown=nom:nom alembic.ini ./
COPY --chown=nom:nom alembic ./alembic
COPY --chown=nom:nom app ./app
COPY --chown=nom:nom docker/metrics_exporter.py docker/wait_for_migrations.py ./docker/
COPY --chown=nom:nom --chmod=0755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/nom \
    NOM_ENVIRONMENT=production \
    NOM_BACKUP_REPO_ROOT=/var/lib/nom/configs \
    NOM_VERSION=${VERSION} \
    GIT_TERMINAL_PROMPT=0

USER 10001:10001
EXPOSE 8000 9808
VOLUME ["/var/lib/nom"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import os,sys,urllib.request; r=os.environ.get('NOM_ROLE','api'); sys.exit(0) if r!='api' else urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"]

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]
CMD ["api"]
