# orchestration/airflow/Dockerfile
#
# Build args:
#   NETWORK_MODE    — "proxy" (local dev, installs corp cert)
#                     "default" (CI/CD, no cert)
#
# Build context: repo root
#
# Local dev:
#   docker build --build-arg NETWORK_MODE=proxy -f orchestration/airflow/Dockerfile -t localhost:5001/airflow-base:dev .
#
# CI/CD:
#   docker build -f orchestration/airflow/Dockerfile -t registry/airflow-base:sha .

ARG NETWORK_MODE=default
ARG PYTHON_VERSION=3.12
ARG AIRFLOW_VERSION=2.11.0

# ── Stage 1a: base with corporate certificate ─────────────────────────────────
FROM apache/airflow:slim-${AIRFLOW_VERSION}-python${PYTHON_VERSION} AS base-proxy

ARG CERT_PATH=/usr/local/share/ca-certificates/nscacert_combined.pem
COPY orchestration/airflow/etc/nscacert_combined.pem ${CERT_PATH}

ENV REQUESTS_CA_BUNDLE=${CERT_PATH}
ENV SSL_CERT_FILE=${CERT_PATH}
ENV CURL_CA_BUNDLE=${CERT_PATH}
ENV HTTPLIB2_CA_CERTS=${CERT_PATH}

# ── Stage 1b: base without certificate ───────────────────────────────────────
FROM apache/airflow:slim-${AIRFLOW_VERSION}-python${PYTHON_VERSION} AS base-default

# ── Stage 2: common build ─────────────────────────────────────────────────────
FROM base-${NETWORK_MODE} AS builder

ARG CERT_PATH=/usr/local/share/ca-certificates/nscacert_combined.pem
ARG AIRFLOW_USER_HOME=/opt/airflow

COPY --from=base-proxy ${CERT_PATH} ${CERT_PATH}

USER root

# ── uv binary (pinned, ~15MB, no curl needed) ─────────────────────────────────
COPY --from=ghcr.io/astral-sh/uv:0.6.16 /uv /uvx /usr/local/bin/

# ── System deps + gcloud ──────────────────────────────────────────────────────
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        curl \
        ca-certificates \
    && update-ca-certificates \
    && ARCH=$(dpkg --print-architecture) \
    && case "${ARCH}" in \
        amd64) GCLOUD_ARCH="linux-x86_64" ;; \
        arm64) GCLOUD_ARCH="linux-arm" ;; \
        *) echo "Unsupported arch: ${ARCH}" && exit 1 ;; \
    esac \
    && GCLOUD_VERSION="google-cloud-cli-538.0.0-${GCLOUD_ARCH}.tar.gz" \
    && curl -fsSL "https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/${GCLOUD_VERSION}" \
        -o /tmp/gcloud.tar.gz \
    && tar -xzf /tmp/gcloud.tar.gz -C /tmp \
    && /tmp/google-cloud-sdk/install.sh --quiet \
        --usage-reporting=false \
        --path-update=false \
    && mv /tmp/google-cloud-sdk ${AIRFLOW_USER_HOME}/google-cloud-sdk \
    && chown -R airflow ${AIRFLOW_USER_HOME}/google-cloud-sdk \
    && rm /tmp/gcloud.tar.gz \
    && apt-get autoremove -yqq --purge \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="${PATH}:${AIRFLOW_USER_HOME}/google-cloud-sdk/bin"

# ── Python deps via uv sync ───────────────────────────────────────────────────
# Switch to root user before installing — avoids site-packages permission error
USER root

WORKDIR ${AIRFLOW_USER_HOME}

COPY pyproject.toml uv.lock ./

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

RUN uv export --frozen --only-group airflow --no-dev --no-hashes \
    | uv pip install --target /home/airflow/.local/lib/python3.12/site-packages -r /dev/stdin \
    && chown -R 50000:0 /home/airflow/.local

USER airflow

# ── gcloud config ─────────────────────────────────────────────────────────────
RUN gcloud config set core/verbosity error \
    && gcloud config set core/log_http false \
    && mkdir -p /opt/airflow/.config/gcloud

# ── Stage 3a: with proxy cert registered in gcloud ───────────────────────────
FROM builder AS builder-proxy

ARG KEY_FILE=orchestration/airflow/etc/sa.gcpkey.json
ARG CERT_PATH=/usr/local/share/ca-certificates/nscacert_combined.pem
ARG AIRFLOW_USER_HOME=/opt/airflow

USER root
RUN mkdir -p ${AIRFLOW_USER_HOME}/etc
COPY ${KEY_FILE} ${AIRFLOW_USER_HOME}/etc/sa.gcpkey.json
RUN chown airflow ${AIRFLOW_USER_HOME}/etc/sa.gcpkey.json \
    && chmod 400 ${AIRFLOW_USER_HOME}/etc/sa.gcpkey.json
USER airflow
RUN gcloud config set core/custom_ca_certs_file ${CERT_PATH}

# ── Stage 3b: no proxy ───────────────────────────────────────────────────────
FROM builder AS builder-default

# ── Final ─────────────────────────────────────────────────────────────────────
FROM builder-${NETWORK_MODE} AS final

ARG AIRFLOW_USER_HOME=/opt/airflow

USER root
COPY orchestration/airflow/scripts/sync_pools.py ${AIRFLOW_USER_HOME}/sync_pools.py
COPY orchestration/airflow/config/pools.json     ${AIRFLOW_USER_HOME}/pools.json
RUN chown airflow \
      ${AIRFLOW_USER_HOME}/sync_pools.py \
      ${AIRFLOW_USER_HOME}/pools.json \
    && chmod +x ${AIRFLOW_USER_HOME}/sync_pools.py

USER airflow

ENTRYPOINT ["/usr/bin/dumb-init", "--", "/entrypoint"]
CMD []