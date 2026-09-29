# syntax=docker/dockerfile:1@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32
FROM ghcr.io/astral-sh/uv:0.11.20@sha256:eaa5f1a3305307aaf9e67fe2bbba1d85ebbb2d8a63bce23af21797bfafbe0f8b AS uv
FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f AS builder
COPY --from=uv /uv /usr/local/bin/uv
ADD --checksum=sha256:3409c6641adb65cb6268d301101ad69226ae1aa147e79377cc1b0b711aa8e538 https://codeload.github.com/huggingface/OpenEnv/tar.gz/4f4c85fb9038f43efc2f51858a27638277f16355 /tmp/source.tar.gz
RUN mkdir /source && tar -xzf /tmp/source.tar.gz -C /source --strip-components=1 \
    && mkdir -p /app && cp -a /source/envs/echo_env /app/env
WORKDIR /app/env
# Preserve the upstream dependency lock; do not resolve newer releases on rebuild.
RUN uv sync --frozen --no-dev --no-editable --no-install-project

FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
# Freeze Debian package resolution for the trixie base image.
RUN printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20260928T000000Z/ trixie main\n' > /etc/apt/sources.list \
    && rm -f /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends iproute2 nftables \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/env /app/env
# VM 0.0.116 does not inherit the image PATH for the canonical command.
RUN ln -s /app/env/.venv/bin/uvicorn /usr/local/bin/uvicorn
ENV PATH="/app/env/.venv/bin:$PATH" PYTHONPATH="/app/env" PYTHONUNBUFFERED=1
LABEL org.opencontainers.image.source="https://github.com/huggingface/OpenEnv" \
      org.opencontainers.image.revision="4f4c85fb9038f43efc2f51858a27638277f16355"
WORKDIR /app/env
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["sh", "-c", "cd /app/env && uvicorn server.app:app --host 0.0.0.0 --port 8000"]
