"""OpenEnv provider lifecycle entry point."""

from __future__ import annotations

import re
import secrets
from copy import deepcopy
from http import HTTPStatus
from math import isfinite
from time import monotonic, sleep
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import httpx

from openenv_openshell._adapter import CreateRequest, SandboxAdapter, connect
from openenv_openshell._compat import ContainerProvider
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
    SandboxReadinessError,
)
from openenv_openshell.metadata import ProviderState
from openenv_openshell.policy import load_policy

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_MAX_PORT = 65535
_NOT_IMPLEMENTED = "OpenShell lifecycle is planned for Milestone 1"


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

    def _sandbox_name_for_image(self, image: str) -> str:
        """Return the configured name or generate a safe, readable unique name."""
        if self.config.sandbox_name is not None:
            return self.config.sandbox_name
        image_without_digest = image.rsplit("@", maxsplit=1)[0]
        image_basename = image_without_digest.rsplit("/", maxsplit=1)[-1]
        image_basename = image_basename.split(":", maxsplit=1)[0]
        prefix = re.sub(r"[^a-z0-9]+", "-", image_basename.casefold()).strip("-")
        prefix = prefix[:48].rstrip("-") or "environment"
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
        adapter = self._connect_adapter()
        self._adapter = adapter
        # Record ownership before create: a lost response can still leave a sandbox.
        self.state = ProviderState(sandbox_name=request.name, image=image)
        error = SandboxCreationError
        try:
            sandbox = adapter.create(request)
            self.state.sandbox_id = sandbox.sandbox_id
            self.state.created = True
            base_url = adapter.service_url(sandbox, request.service_name)
            if base_url is None:
                msg = "OpenShell did not return the requested service URL"
                raise SandboxCreationError(msg)  # noqa: TRY301 - Stage-specific failure enters rollback.
            self._validate_service_url(base_url)
            self.state.base_url = base_url
            error = SandboxReadinessError
            ready = adapter.wait_ready(
                request.name,
                workspace=request.workspace,
                timeout_s=self.config.startup_timeout_s,
            )
            if ready.sandbox_id != sandbox.sandbox_id:
                msg = "OpenShell readiness returned a different sandbox identity"
                raise SandboxReadinessError(msg)  # noqa: TRY301 - Stage-specific failure enters rollback.
        except Exception:  # noqa: BLE001 - Sanitize runtime failures and always roll back.
            self._cleanup_failed_start(adapter, request.name)
            # Do not expose upstream exception text, workload argv, or route data.
            msg = "OpenShell sandbox startup failed"
            raise error(msg) from None
        return base_url

    def _cleanup_failed_start(self, adapter: SandboxAdapter, name: str) -> None:
        """Best-effort rollback; uncertain deletion retains ownership for retry."""
        try:
            if not self.config.keep_sandbox:
                deletion = adapter.delete(name, workspace=self.config.workspace)
                identity = self.state.sandbox_id or deletion.sandbox_id
                if identity is not None:
                    adapter.wait_deleted(
                        name,
                        workspace=self.config.workspace,
                        expected_sandbox_id=identity,
                        timeout_s=self.config.deletion_timeout_s,
                    )
                    self.state.deleted = True
                elif deletion.outcome in {"completed", "already_absent"}:
                    self.state.deleted = True
        except Exception:  # noqa: BLE001 - Rollback must preserve the startup failure.
            return
        if self.config.keep_sandbox or self.state.deleted:
            try:
                adapter.close()
            except Exception:  # noqa: BLE001 - Preserve the startup failure.
                return
            self._adapter = None

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
        """Delete the owned sandbox; this will be idempotent in Milestone 1."""
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def wait_for_ready(self, base_url: str, timeout_s: float = 30.0) -> None:
        """Wait until the OpenEnv server's health endpoint is ready."""
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
                        return
                except httpx.RequestError:
                    # Transport messages may contain credentials or URL data.
                    pass
                remaining = deadline - monotonic()
                if remaining > 0:
                    sleep(min(self.config.health_poll_interval_s, remaining))

        msg = "OpenEnv health readiness timed out"
        raise OpenEnvReadinessTimeout(msg)
