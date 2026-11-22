FROM python:3.15.2-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS base
COPY --from=ghcr.io/astral-sh/uv:0.13.8@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85 /uv /uvx /bin/

# litellm fetches its model cost map over the network at import time, so a
# third-party change to that map can change runtime behavior with no image
# change and no version bump. Use the map bundled with the litellm pinned in
# uv.lock so every stage (test and runtime) behaves how it was built and tested
# rather than tracking today's remote data; new models then arrive with a
# deliberate litellm bump in the lockfile.
ENV LITELLM_LOCAL_MODEL_COST_MAP=True

RUN apt-get update && apt-get install --no-install-recommends -y git curl && apt-get clean && rm -rf /var/lib/apt/lists/*

# open-code-review (ocr) is pinned by version and per-arch SHA-256 taken from the
# upstream release's sha256sum.txt, so the binary cannot change without a
# deliberate edit here. Bump OCR_VERSION and both hashes together with the
# vendored third_party/open_code_review/ in the same commit. ocr needs git >= 2.41.
ARG TARGETARCH
ARG OCR_VERSION=v1.13.12
ARG OCR_SHA256_AMD64=673ed6bfd905bf68383269e78945b9d873a5c8c0931fce6e86374ca58df0b8b1
ARG OCR_SHA256_ARM64=178b1a926616f69522a7dc18a69513841813132f98accc35db960276cd53408d
RUN set -eu; \
    case "${TARGETARCH}" in \
      amd64) ocr_sha256="${OCR_SHA256_AMD64}" ;; \
      arm64) ocr_sha256="${OCR_SHA256_ARM64}" ;; \
      *) echo "unsupported TARGETARCH: '${TARGETARCH}'" >&2; exit 1 ;; \
    esac; \
    ocr_asset="opencodereview-linux-${TARGETARCH}"; \
    curl -fsSL -o "/tmp/${ocr_asset}" "https://github.com/alibaba/open-code-review/releases/download/${OCR_VERSION}/${ocr_asset}"; \
    echo "${ocr_sha256}  /tmp/${ocr_asset}" | sha256sum -c -; \
    install -m 0755 "/tmp/${ocr_asset}" /usr/local/bin/ocr; \
    rm -f "/tmp/${ocr_asset}"; \
    ocr version; \
    set -- $(git --version | sed -n 's/^git version \([0-9][0-9]*\)\.\([0-9][0-9]*\).*/\1 \2/p'); \
    if [ "$#" -ne 2 ] || { [ "$1" -lt 2 ] || { [ "$1" -eq 2 ] && [ "$2" -lt 41 ]; }; }; then \
      echo "git >= 2.41 required for ocr, found: $(git --version)" >&2; exit 1; \
    fi

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --extra all
# Keep documentation changes from invalidating the dependency layer.
COPY docs docs
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app

# Use a dedicated identity for long-running services; preserve the runner, CLI
# and test mount/install contracts. Grant UID/GID 10001 read access to mounted
# secrets and write access to custom output, analytics and database paths.
FROM base AS service
RUN groupadd --gid 10001 pragent && \
    useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin pragent && \
    mkdir -p /app/pr-agent-outputs /app/lancedb && \
    chown pragent:pragent /app/pr-agent-outputs /app/lancedb
ENV HOME=/home/pragent
USER 10001:10001

FROM service AS github_app
COPY pr_agent pr_agent
CMD ["python", "-m", "gunicorn", "-k", "uvicorn_worker.UvicornWorker", "-c", "pr_agent/servers/gunicorn_config.py", "--forwarded-allow-ips", "*", "pr_agent.servers.github_app:app"]

FROM service AS bitbucket_app
COPY pr_agent pr_agent
CMD ["python", "pr_agent/servers/bitbucket_app.py"]

FROM service AS bitbucket_server_webhook
COPY pr_agent pr_agent
CMD ["python", "-m", "gunicorn", "-k", "uvicorn_worker.UvicornWorker", "-c", "pr_agent/servers/gunicorn_config.py", "--forwarded-allow-ips", "*", "pr_agent.servers.bitbucket_server_webhook:app"]

FROM service AS github_polling
COPY pr_agent pr_agent
CMD ["python", "pr_agent/servers/github_polling.py"]

FROM base AS github_action
COPY pr_agent pr_agent
COPY github_action/entrypoint.sh /
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

FROM service AS gitlab_webhook
COPY pr_agent pr_agent
CMD ["python", "-m", "gunicorn", "-k", "uvicorn_worker.UvicornWorker", "-c", "pr_agent/servers/gunicorn_config.py", "--forwarded-allow-ips", "*", "pr_agent.servers.gitlab_webhook:app"]

FROM service AS azure_devops_webhook
COPY pr_agent pr_agent
CMD ["python", "pr_agent/servers/azuredevops_server_webhook.py"]

FROM service AS gitea_app
COPY pr_agent pr_agent
CMD ["python", "-m", "gunicorn", "-k", "uvicorn_worker.UvicornWorker", "-c", "pr_agent/servers/gunicorn_config.py","pr_agent.servers.gitea_app:app"]

FROM service AS mosaico_agent
COPY pr_agent pr_agent
EXPOSE 9000
CMD ["python", "pr_agent/mosaico/server.py"]


FROM base AS test
# The base stage pins LITELLM_LOCAL_MODEL_COST_MAP for every stage; kept here
# only as documentation that the unit suite keys off the bundled cost map.
RUN uv sync --frozen --no-install-project --extra all
COPY pr_agent pr_agent
COPY tests tests
# Config the unit suite asserts against, copied file by file so an unrelated
# workflow edit does not invalidate this layer.
COPY .github/workflows/build-and-test.yaml .github/workflows/build-and-test.yaml
COPY docker/Dockerfile docker/Dockerfile
COPY docker/Dockerfile.lambda docker/Dockerfile.lambda
COPY docker/mosaico docker/mosaico
# Loaded by its unit test.
COPY scripts/structural_reach_producer.py scripts/structural_reach_producer.py
# Read by the docs guards: the URL checker, the pages that link into the docs site,
# and the packaging inputs that must ship every /help page suffix. Kept last so a
# README edit only rebuilds these final layers.
COPY scripts/check_docs_urls.py scripts/check_docs_urls.py
COPY scripts/generate_config_reference.py scripts/generate_config_reference.py
COPY README.md CONTRIBUTING.md SECURITY.md .dockerignore ./
COPY MANIFEST.in setup.py ./

FROM base AS cli
COPY pr_agent pr_agent
COPY third_party/open_code_review third_party/open_code_review
RUN uv sync --frozen --no-dev --extra all && ln -s /app/.venv/bin/pr-agent /usr/local/bin/pr-agent
ENTRYPOINT ["python", "pr_agent/cli.py"]
