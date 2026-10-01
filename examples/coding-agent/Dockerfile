# syntax=docker/dockerfile:1@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32
# Upstream OpenEnv coding_env for the I8 demo, pinned like the EchoEnv fixture.
# Build from the repository root:
#   docker build -t openenv-openshell-coding:i8 examples/coding-agent
FROM ghcr.io/astral-sh/uv:0.11.20@sha256:eaa5f1a3305307aaf9e67fe2bbba1d85ebbb2d8a63bce23af21797bfafbe0f8b AS uv
FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f AS builder
COPY --from=uv /uv /usr/local/bin/uv
ADD --checksum=sha256:3409c6641adb65cb6268d301101ad69226ae1aa147e79377cc1b0b711aa8e538 https://codeload.github.com/huggingface/OpenEnv/tar.gz/4f4c85fb9038f43efc2f51858a27638277f16355 /tmp/source.tar.gz
RUN mkdir /source && tar -xzf /tmp/source.tar.gz -C /source --strip-components=1 \
    && mkdir -p /app && cp -a /source/envs/coding_env /app/env
WORKDIR /app/env
# Preserve the upstream lock and use the base image's interpreter.
ENV UV_PYTHON=/usr/local/bin/python3.12 UV_PYTHON_DOWNLOADS=never
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
# Freeze Debian package resolution for the trixie base image.
RUN printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20260928T000000Z/ trixie main\n' > /etc/apt/sources.list \
    && rm -f /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends iproute2 nftables \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/env /app/env
# The VM lane does not inherit the image PATH for the initial command.
RUN ln -s /app/env/.venv/bin/uvicorn /usr/local/bin/uvicorn
# Strict policy identity, writable workspace, and SYNTHETIC world-readable
# canaries: Unix permissions allow the reads, so only policy can deny them.
RUN groupadd --gid 1000 sandbox \
    && useradd --uid 1000 --gid sandbox --no-create-home --shell /usr/sbin/nologin sandbox \
    && mkdir -p /workspace /root/.ssh /host/etc \
    && chown sandbox:sandbox /workspace \
    && printf 'i8-synthetic-canary\n' > /root/.ssh/id_rsa \
    && printf 'i8-synthetic-canary\n' > /host/etc/shadow \
    && chmod 755 /root /root/.ssh /host /host/etc \
    && chmod 644 /root/.ssh/id_rsa /host/etc/shadow
ENV PATH="/app/env/.venv/bin:$PATH" PYTHONUNBUFFERED=1
LABEL org.opencontainers.image.source="https://github.com/huggingface/OpenEnv" \
      org.opencontainers.image.revision="4f4c85fb9038f43efc2f51858a27638277f16355"
WORKDIR /workspace
EXPOSE 8000
CMD ["uvicorn", "coding_env.server.app:app", "--host", "0.0.0.0", "--port", "8000"]
