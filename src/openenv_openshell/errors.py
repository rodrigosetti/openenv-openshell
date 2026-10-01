"""Provider-specific exceptions with stable public meanings."""


class OpenShellProviderError(RuntimeError):
    """Base class for provider failures."""


class OpenShellConnectionError(OpenShellProviderError):
    """Raised when the provider cannot communicate with OpenShell."""


class SandboxCreationError(OpenShellProviderError):
    """Raised when sandbox creation fails."""


class SandboxReadinessError(OpenShellProviderError):
    """Raised when an OpenShell sandbox does not become ready."""


class OpenEnvReadinessTimeout(OpenShellProviderError):  # noqa: N818
    """Raised when the OpenEnv health endpoint does not become ready."""


class ServiceAccessError(OpenShellProviderError):
    """Raised when TLS rejects access the OpenEnv client cannot provide.

    Examples are an untrusted route certificate or a required TLS client
    certificate. Retrying cannot help.
    """


class SandboxDeletionError(OpenShellProviderError):
    """Raised when an owned sandbox cannot be deleted."""


class PolicyConfigurationError(OpenShellProviderError):
    """Raised when an explicit policy cannot be loaded or validated."""
