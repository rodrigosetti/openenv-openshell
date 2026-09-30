# Extend the locally validated EchoEnv image; no real host files or secrets.
ARG ECHO_IMAGE=openenv-openshell-echo:s3
FROM ${ECHO_IMAGE}
USER root
RUN mkdir -p /root/.ssh /host/etc /workspace \
    && printf 'sec5-synthetic-canary\n' > /root/.ssh/id_rsa \
    && printf 'sec5-synthetic-canary\n' > /host/etc/shadow \
    && chmod 755 /root /root/.ssh /host /host/etc /workspace \
    && chown 1000:1000 /workspace \
    && chmod 644 /root/.ssh/id_rsa /host/etc/shadow
