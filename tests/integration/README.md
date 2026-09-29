# Integration tests

Tests in this directory require a real OpenShell gateway and external resources.
Mark each test with `@pytest.mark.integration`; they are excluded from the
default unit-test run configured in `pyproject.toml`.

