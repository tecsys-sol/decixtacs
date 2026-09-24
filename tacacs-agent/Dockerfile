# syntax=docker/dockerfile:1.7
# tac_plus-ng (event-driven-servers by Marc Huber) + NetworkOps Manager agent.
#
# The platform renders tac_plus-ng.cfg; the agent in this image pulls it, validates it with
# `tac_plus-ng -P`, swaps it in atomically, SIGHUPs tac_plus-ng and reports back. It also ships
# the access/authz/accounting logs and uploads session recordings from a spool directory.
#
#   docker build -t networkops/tacacs ./tacacs-agent
#   docker run -p 49:49 -e NOM_AGENT_API_URL=https://nom.example.net -e NOM_AGENT_TOKEN=nomagent_... networkops/tacacs

ARG PYTHON_IMAGE=python:3.12-slim-bookworm

# ---------------------------------------------------------------------------------------------
# Build tac_plus-ng from source.
# ---------------------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS tacplus
ARG EDS_REPO=https://github.com/MarcJHuber/event-driven-servers.git
# Pin a commit or tag for reproducible builds (default: the default branch at build time).
ARG EDS_REF=master
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential git ca-certificates perl pkg-config \
      libpcre2-dev libssl-dev zlib1g-dev libc-ares-dev libldap-dev libsasl2-dev \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git clone --filter=blob:none "$EDS_REPO" event-driven-servers
WORKDIR /src/event-driven-servers
RUN git checkout "$EDS_REF" && git rev-parse HEAD > /EDS_COMMIT
# Record everything `make install` adds under /usr/local so the runtime stage receives exactly
# those files (and not the builder's Python installation that also lives in /usr/local).
RUN touch /tmp/.before-install \
 && ./configure tac_plus-ng \
 && make \
 && make install \
 && find /usr/local -newer /tmp/.before-install \( -type f -o -type l \) -print > /tmp/installed.txt \
 && tar -cf /tmp/eds.tar -T /tmp/installed.txt \
 && test -x /usr/local/sbin/tac_plus-ng

# ---------------------------------------------------------------------------------------------
# Agent wheel.
# ---------------------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS agent
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m venv /opt/venv && /opt/venv/bin/pip install .

# ---------------------------------------------------------------------------------------------
# Runtime.
# ---------------------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime
ARG VERSION=dev
ARG VCS_REF=unknown
LABEL org.opencontainers.image.title="networkops-manager-tacacs" \
      org.opencontainers.image.description="tac_plus-ng + NetworkOps Manager agent" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.source="https://github.com/tecsys-sol/decixtacs"

# perl + Net::LDAP: mavis LDAP/AD backend script (mavis_tacplus-ng_ldap.pl) for servers with
# ldap_backend=true. tini: PID 1 / zombie reaping.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      tini ca-certificates perl libnet-ldap-perl libio-socket-ssl-perl libauthen-sasl-perl \
      libpcre2-8-0 libssl3 zlib1g libc-ares2 libldap-2.5-0 libsasl2-2 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=tacplus /tmp/eds.tar /tmp/eds.tar
COPY --from=tacplus /EDS_COMMIT /usr/local/share/doc/event-driven-servers.commit
RUN tar -xf /tmp/eds.tar -C / && rm /tmp/eds.tar && ldconfig \
 && groupadd --system --gid 10002 tacacs \
 && useradd --system --uid 10002 --gid tacacs --home-dir /var/lib/nom-agent --shell /usr/sbin/nologin tacacs \
 && mkdir -p /etc/tac_plus-ng /var/log/tac_plus-ng /var/lib/nom-agent /var/spool/nom-recordings /run/nom \
             /usr/local/share/nom-tacacs-agent \
 && chown -R tacacs:tacacs /etc/tac_plus-ng /var/log/tac_plus-ng /var/lib/nom-agent /var/spool/nom-recordings /run/nom

COPY --from=agent /opt/venv /opt/venv
COPY docker/tac_plus-ng.bootstrap.cfg /usr/local/share/nom-tacacs-agent/tac_plus-ng.bootstrap.cfg

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NOM_AGENT_TACPLUS_BIN=/usr/local/sbin/tac_plus-ng \
    NOM_AGENT_CONFIG_PATH=/etc/tac_plus-ng/tac_plus-ng.cfg \
    NOM_AGENT_PIDFILE=/run/nom/tac_plus-ng.pid \
    NOM_AGENT_RELOAD_MODE=signal \
    NOM_AGENT_STATE_DIR=/var/lib/nom-agent \
    NOM_AGENT_SPOOL_DIR=/var/spool/nom-recordings

# Port 49 as a non-root user: Docker (>= 20.10) sets net.ipv4.ip_unprivileged_port_start=0 in
# containers; on Kubernetes set the same (safe) sysctl in the pod securityContext.
USER 10002:10002
EXPOSE 49/tcp
VOLUME ["/etc/tac_plus-ng", "/var/log/tac_plus-ng", "/var/lib/nom-agent", "/var/spool/nom-recordings"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD ["nom-tacacs-agent", "healthcheck"]
ENTRYPOINT ["/usr/bin/tini", "--", "nom-tacacs-agent"]
CMD ["supervise"]
