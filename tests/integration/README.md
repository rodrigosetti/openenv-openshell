# Integration tests

Tests in this directory exercise real transports or an OpenShell runtime.
Mark each test with `@pytest.mark.integration`; they are excluded from the
default unit-test run configured in `pyproject.toml`.

`test_http_readiness.py` uses a local HTTP server and needs no OpenShell gateway:

```bash
uv run pytest -m integration tests/integration/test_http_readiness.py --no-cov
```

Before running tests that require an OpenShell gateway, complete the
[local OpenShell setup](../../docs/local-openshell-testing.md) and ensure
`make openshell-smoke` passes.
