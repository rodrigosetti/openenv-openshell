"""OpenEnv provider lifecycle entry point."""

from __future__ import annotations

import logging
import re
import secrets
import ssl
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from http import HTTPStatus
from math import isfinite
from time import monotonic, sleep
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import httpx

from openenv_openshell._adapter import (
    CreateCollisionError,
    CreateRequest,
    DeleteNotSentError,
    SandboxAdapter,
    connect,
)
from openenv_openshell._compat import ContainerProvider
from openenv_openshell._naming import MAX_SANDBOX_NAME_LENGTH
from openenv_openshell.config import (
    OpenShellProviderConfig,
    OpenShellResources,
    Policy,
    validate_command,
)
from openenv_openshell.errors import (
    OpenEnvReadinessTimeout,
    OpenShellProviderError,
    SandboxCreationError,
    SandboxDeletionError,
    SandboxReadinessError,
    ServiceAccessError,
)
from openenv_openshell.metadata import (
    OpenShellRunMetadata,
    ProviderState,
    package_version,
)
from openenv_openshell.policy import load_policy, policy_digest

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_MAX_PORT = 65535
# Reserve "openenv-" and a six-hex suffix within the configured name limit.
_GENERATED_IMAGE_PREFIX_LENGTH = MAX_SANDBOX_NAME_LENGTH - len("openenv--") - 6
_LOGGER = logging.getLogger("openenv_openshell")
# TLS alerts for a route that demands a client certificate (TLS 1.3 and 1.2).
_CLIENT_CERT_ALERTS = frozenset(
    {"TLSV13_ALERT_CERTIFICATE_REQUIRED", "SSLV3_ALERT_HANDSHAKE_FAILURE"}
)


def _service_access_failure(error: BaseException) -> str | None:
    """Describe a non-retryable TLS rejection without echoing transport text."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ssl.SSLCertVerificationError):
            return "OpenShell service route certificate is not trusted"
        if isinstance(current, ssl.SSLError) and current.reason in _CLIENT_CERT_ALERTS:
            return "OpenShell service route requires a TLS client certificate"
        current = current.__cause__ or current.__context__
    return None


class OpenShellProvider(ContainerProvider):
    """Run one OpenEnv environment server in an OpenShell sandbox."""

    def __init__(  # noqa: PLR0913 - Mirrors the specified public constructor.
        self,
        *,
        workspace: str = "default",
        sandbox_name: str | None = None,
        policy: Policy = None,
        command: Sequence[str] | None = None,
        service_port: int = 8000,
        service_name: str = "",
        startup_timeout_s: float = 120.0,
        deletion_timeout_s: float = 60.0,
        health_poll_interval_s: float = 0.5,
        health_request_timeout_s: float = 2.0,
        gateway: str | None = None,
        keep_sandbox: bool = False,
        labels: Mapping[str, str] | None = None,
        providers: Sequence[str] | None = None,
        resources: OpenShellResources | None = None,
    ) -> None:
        """Create a provider without contacting an OpenShell gateway."""
        self.config = OpenShellProviderConfig(
            workspace=workspace,
            sandbox_name=sandbox_name,
            policy=policy,
            command=command,
            service_port=service_port,
            service_name=service_name,
            startup_timeout_s=startup_timeout_s,
            deletion_timeout_s=deletion_timeout_s,
            health_poll_interval_s=health_poll_interval_s,
            health_request_timeout_s=health_request_timeout_s,
            gateway=gateway,
            keep_sandbox=keep_sandbox,
            labels={} if labels is None else labels,
            providers=() if providers is None else providers,
            resources=resources,
        )
        self.state = ProviderState()
        self._adapter: SandboxAdapter | None = None
        self._metadata: OpenShellRunMetadata | None = None
        self._deletion_attempted = False

    @property
    def metadata(self) -> OpenShellRunMetadata | None:
        """Return the latest immutable run snapshot, retained after cleanup."""
        return self._metadata

    def _sandbox_name_for_image(self, image: str) -> str:
        """Return the configured name or generate a safe, readable unique name."""
        if self.config.sandbox_name is not None:
            return self.config.sandbox_name
        image_without_digest = image.rsplit("@", maxsplit=1)[0]
        image_basename = image_without_digest.rsplit("/", maxsplit=1)[-1]
        image_basename = image_basename.split(":", maxsplit=1)[0]
        prefix = re.sub(r"[^a-z0-9]+", "-", image_basename.casefold()).strip("-")
        prefix = prefix[:_GENERATED_IMAGE_PREFIX_LENGTH].rstrip("-") or "env"
        return f"openenv-{prefix}-{secrets.token_hex(3)}"

    def _connect_adapter(self) -> SandboxAdapter:
        """Select the registered gateway only when lifecycle work needs a client."""
        return connect(gateway=self.config.gateway)

    def _create_request(
        self,
        image: str,
        *,
        policy: Mapping[str, object] | None,
        port: int | None = None,
        env_vars: Mapping[str, str] | None = None,
        **kwargs: object,
    ) -> CreateRequest:
        """Prepare adapter inputs with an already resolved, explicit policy.

        Policy loading belongs to the policy boundary. None requests OpenShell's
        image/default policy only when no explicit policy was configured.
        """
        if kwargs:
            msg = "Unsupported start_container options"
            raise ValueError(msg)
        if not isinstance(image, str) or not image.strip() or "\x00" in image:  # pyright: ignore[reportUnnecessaryIsInstance]
            msg = "image must be a non-empty OCI image reference"
            raise ValueError(msg)
        target_port = self.config.service_port if port is None else port
        if (
            isinstance(target_port, bool)
            or not isinstance(target_port, int)  # pyright: ignore[reportUnnecessaryIsInstance]
            or not 1 <= target_port <= _MAX_PORT
        ):
            msg = "port must be an integer from 1 through 65535"
            raise ValueError(msg)
        command = validate_command(self.config.command)
        environment = {} if env_vars is None else dict(env_vars)
        for key, value in environment.items():
            if (
                not isinstance(key, str)  # pyright: ignore[reportUnnecessaryIsInstance]
                or not isinstance(value, str)  # pyright: ignore[reportUnnecessaryIsInstance]
                or not key
                or "=" in key
                or "\x00" in key
                or "\x00" in value
            ):
                msg = "env_vars must contain valid environment names and string values"
                raise ValueError(msg)
        labels = dict(self.config.labels)
        labels.update(
            {"managed-by": "openenv-openshell", "openenv.provider": "openshell"}
        )
        return CreateRequest(
            workspace=self.config.workspace,
            name=self._sandbox_name_for_image(image),
            image=image,
            command=command,
            environment=MappingProxyType(environment),
            service_name=self.config.service_name,
            target_port=target_port,
            labels=MappingProxyType(labels),
            providers=tuple(self.config.providers),
            resources=self.config.resources,
            policy=None if policy is None else MappingProxyType(deepcopy(dict(policy))),
        )

    def start_container(
        self,
        image: str,
        port: int | None = None,
        env_vars: Mapping[str, str] | None = None,
        **kwargs: Any,  # noqa: ANN401 - Required by the upstream provider contract.
    ) -> str:
        """Create the sandbox and return its OpenShell-managed service URL."""
        if self._adapter is not None or (
            self.state.sandbox_name is not None and not self.state.deleted
        ):
            msg = "Provider already owns a sandbox; clean it up before starting again"
            raise OpenShellProviderError(msg)
        policy = None if self.config.policy is None else load_policy(self.config.policy)
        request = self._create_request(
            image, policy=policy, port=port, env_vars=env_vars, **kwargs
        )
        submitted_policy_digest = (
            None if request.policy is None else policy_digest(request.policy)
        )
        # Prepare state before connecting so state construction cannot leak a client.
        state = ProviderState(sandbox_name=request.name, image=image)
        adapter = self._connect_adapter()
        self._adapter = adapter
        # Retain the attempted name for diagnosis; it is not proof of ownership.
        self.state = state
        self._metadata = None
        self._deletion_attempted = False
        error = SandboxCreationError
        created_identity: str | None = None
        try:
            _LOGGER.info("sandbox.create.started")
            sandbox = adapter.create(request)
            created_identity = sandbox.sandbox_id
            self.state.sandbox_id = sandbox.sandbox_id
            self.state.created = True
            created_at = datetime.now(UTC)
            _LOGGER.info("sandbox.create.completed")
            base_url = adapter.service_url(sandbox, request.service_name)
            if base_url is None:
                msg = "OpenShell did not return the requested service URL"
                raise SandboxCreationError(msg)  # noqa: TRY301 - Stage-specific failure enters rollback.
            self._validate_service_url(base_url)
            self.state.base_url = base_url
            self._metadata = OpenShellRunMetadata(
                sandbox_name=request.name,
                sandbox_id=sandbox.sandbox_id,
                workspace=request.workspace,
                image=image,
                service_url=base_url,
                policy_digest=submitted_policy_digest,
                created_at=created_at,
                openenv_provider_version=package_version("openenv-openshell"),
                openshell_version=package_version("openshell"),
                openenv_version=package_version("openenv"),
            )
            _LOGGER.info("service.exposed")
            error = SandboxReadinessError
            ready = adapter.wait_ready(
                request.name,
                workspace=request.workspace,
                timeout_s=self.config.startup_timeout_s,
            )
            if ready.sandbox_id != sandbox.sandbox_id:
                msg = "OpenShell readiness returned a different sandbox identity"
                raise SandboxReadinessError(msg)  # noqa: TRY301 - Stage-specific failure enters rollback.
        except CreateCollisionError:
            failure = self._rollback_create_collision()
            raise failure from None
        except BaseException as startup_failure:
            if created_identity is not None:
                self.state.sandbox_id = created_identity
            if isinstance(startup_failure, Exception):
                # Do not expose runtime text, workload argv, or route data.
                failure = error("OpenShell sandbox startup failed")
                self._cleanup_failed_start(failure)
                raise failure from None
            # Preserve cancellation/exit semantics; interrupted create does not
            # prove ownership, so public cleanup still refuses deletion by name.
            self._cleanup_failed_start(startup_failure)
            raise
        _LOGGER.info("sandbox.ready")
        return base_url

    def _rollback_create_collision(self) -> SandboxCreationError:
        """Release only the client when the attempted name belongs to another owner."""
        self.state = ProviderState()
        failure = SandboxCreationError(
            "OpenShell sandbox name is already in use; choose another name"
        )
        self._cleanup_failed_start(failure)
        return failure

    def _cleanup_failed_start(self, failure: BaseException) -> None:
        """Use public cleanup without replacing the primary startup failure."""
        try:
            self.stop_container()
        except BaseException:  # noqa: BLE001 - Cleanup must not replace the primary failure.
            # Notes appear in tracebacks without exposing runtime errors or inputs.
            if self.state.sandbox_name is not None and not self.state.sandbox_id:
                failure.add_note(
                    "Sandbox ownership is unconfirmed; operator inspection required "
                    "before removing the attempted name in provider.state.sandbox_name"
                )
            else:
                failure.add_note(
                    "OpenShell sandbox cleanup failed; "
                    "call stop_container again to retry"
                )

    def _record_deletion(self) -> None:
        """Record confirmed absence, independently of releasing the SDK client."""
        if self._metadata is not None:
            self._metadata = replace(self._metadata, deleted_at=datetime.now(UTC))
        _LOGGER.info("sandbox.delete.completed")

    @staticmethod
    def _validate_service_url(base_url: str) -> httpx.URL:
        """Reject unusable routes without echoing secret URL data."""
        try:
            url = httpx.URL(base_url)
        except httpx.InvalidURL:
            msg = "base_url must be an absolute HTTP(S) service URL"
            raise ValueError(msg) from None
        if (
            url.scheme not in {"http", "https"}
            or not url.host
            or url.userinfo
            or url.query
            or url.fragment
        ):
            msg = (
                "base_url must be an absolute HTTP(S) URL "
                "without credentials, query, or fragment"
            )
            raise ValueError(msg)
        return url

    def stop_container(self) -> None:
        """Release ownership after deletion; retain uncertain cleanup for retry.

        With keep_sandbox, release the client and local ownership without deleting
        the runtime. Failures are sanitized and can be retried by calling again.
        """
        name = self.state.sandbox_name
        if name is None and self._adapter is None:
            return
        try:
            if (
                name is not None
                and not self.state.deleted
                and not self.config.keep_sandbox
            ):
                identity = self.state.sandbox_id
                if not identity:
                    # Local resources do not establish runtime ownership. Release
                    # them without reconnecting or discarding inspection state.
                    if self._adapter is not None:
                        self._adapter.close()
                        self._adapter = None
                    msg = (
                        "Sandbox ownership is unconfirmed; operator inspection required"
                    )
                    raise SandboxDeletionError(msg)  # noqa: TRY301 - Sanitize all cleanup failures below.
                if self._adapter is None:
                    self._adapter = self._connect_adapter()
                _LOGGER.info("sandbox.delete.started")
                if not self._deletion_attempted:
                    # A lost delete reply may still have been applied. Never send
                    # a second name-based delete; it could target a replacement.
                    self._deletion_attempted = True
                    try:
                        self._adapter.delete(
                            name,
                            workspace=self.config.workspace,
                            expected_sandbox_id=identity,
                        )
                    except DeleteNotSentError:
                        # Only a proven preflight failure permits the first
                        # delete to be retried after checking ownership again.
                        self._deletion_attempted = False
                        raise
                self._adapter.wait_deleted(
                    name,
                    workspace=self.config.workspace,
                    expected_sandbox_id=identity,
                    timeout_s=self.config.deletion_timeout_s,
                )
                self.state.deleted = True
                self.state.ready = False
                self._record_deletion()
            if self._adapter is not None:
                self._adapter.close()
        except Exception:  # noqa: BLE001 - SDK errors may contain credentials.
            _LOGGER.warning("provider.cleanup.failed")
            msg = (
                "OpenShell sandbox cleanup failed; call stop_container again to retry "
                "confirmation or inspect the attempted sandbox with an operator"
            )
            raise SandboxDeletionError(msg) from None
        self._adapter = None
        self.state = ProviderState(deleted=self.state.deleted)

    def close(self) -> None:
        """Delete the owned sandbox and release resources, including on context exit.

        This has the same keep_sandbox and retry semantics as stop_container.
        The inherited OpenEnv context manager calls close without suppressing
        exceptions. Cleanup failures retain ownership for an explicit retry.
        """
        self.stop_container()

    def wait_for_ready(self, base_url: str, timeout_s: float = 30.0) -> None:
        """Wait until the OpenEnv server's health endpoint is ready.

        Raises ServiceAccessError without retrying when TLS rejects the route's
        certificate or requires a client certificate, since an unmodified
        OpenEnv client cannot satisfy either. HTTP statuses, including 401 and
        403, keep polling until the deadline.
        """
        if isinstance(timeout_s, bool) or not isfinite(timeout_s) or timeout_s <= 0:
            msg = "timeout_s must be a positive finite number"
            raise ValueError(msg)
        url = self._validate_service_url(base_url)

        health_url = url.copy_with(raw_path=url.raw_path.rstrip(b"/") + b"/health")
        self.state.ready = False
        deadline = monotonic() + timeout_s
        with httpx.Client(follow_redirects=False) as client:
            while (remaining := deadline - monotonic()) > 0:
                request_timeout = min(self.config.health_request_timeout_s, remaining)
                try:
                    # Only headers matter; do not buffer an unbounded health body.
                    with client.stream(
                        "GET", health_url, timeout=request_timeout
                    ) as response:
                        status = response.status_code
                    if status == HTTPStatus.OK and monotonic() < deadline:
                        self.state.ready = True
                        metadata = self.metadata
                        if metadata is not None and base_url == self.state.base_url:
                            self._metadata = replace(
                                metadata, ready_at=datetime.now(UTC)
                            )
                        _LOGGER.info("openenv.health.ready")
                        return
                    denied = None
                except httpx.RequestError as error:
                    # Transport messages may contain credentials or URL data.
                    denied = _service_access_failure(error)
                if denied is not None:
                    # Raised outside the handler so no transport error is chained.
                    _LOGGER.warning("openenv.health.access_denied")
                    raise ServiceAccessError(denied)
                remaining = deadline - monotonic()
                if remaining > 0:
                    sleep(min(self.config.health_poll_interval_s, remaining))

        msg = "OpenEnv health readiness timed out"
        raise OpenEnvReadinessTimeout(msg)
