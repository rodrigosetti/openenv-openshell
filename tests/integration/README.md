# Integration tests

Tests in this directory require a real OpenShell gateway and external resources.
Mark each test with `@pytest.mark.integration`; they are excluded from the
default unit-test run configured in `pyproject.toml`.

Before running them, complete the
[local OpenShell setup](../../docs/local-openshell-testing.md) and ensure
`make openshell-smoke` passes.

For the native arm64 EchoEnv image, follow the [S3 build and validation
guide](../../docs/echo-env-image.md). Its opt-in test requires
`OPENENV_OPENSHELL_ECHO_IMAGE_ID` and CLI/gateway 0.0.116; without the image ID
it skips before touching a runtime. This image-only probe uses `--no-cov`
because it does not execute provider code. Unit coverage remains enforced by
`make check`.
