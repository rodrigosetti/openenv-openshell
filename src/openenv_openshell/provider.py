"""OpenEnv provider lifecycle entry point."""

from __future__ import annotations

import re
import secrets
from http import HTTPStatus
from math import isfinite
from time import monotonic, sleep
from typing import TYPE_CHECKING, Any

import httpx

from openenv_openshell._compat import ContainerProvider
from openenv_openshell.config import (
    OpenShellProviderConfig,
    OpenShellResources,
    Policy,
)
from openenv_openshell.errors import OpenEnvReadinessTimeout
from openenv_openshell.metadata import ProviderState

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_NOT_IMPLEMENTED = "OpenShell lifecycle is planned for Milestone 1"


class OpenShellProvider(ContainerProvider):
    """Run one OpenEnv environment server in an OpenShell sandbox."""

    def __init__(  # noqa: PLR0913 - Mirrors the specified public constructor.
        self,
        *,
        workspace: str = "default",
        sandbox_name: str | None = None,
        policy: Policy = None,
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

    def start_container(
        self,
        image: str,
        port: int | None = None,
        env_vars: Mapping[str, str] | None = None,
        **kwargs: Any,  # noqa: ANN401 - Required by the upstream provider contract.
    ) -> str:
        """Create the sandbox and return its OpenShell-managed service URL."""
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def stop_container(self) -> None:
        """Delete the owned sandbox; this will be idempotent in Milestone 1."""
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def wait_for_ready(self, base_url: str, timeout_s: float = 30.0) -> None:
        """Wait until the OpenEnv server's health endpoint is ready."""
        if isinstance(timeout_s, bool) or not isfinite(timeout_s) or timeout_s <= 0:
            msg = "timeout_s must be a positive finite number"
            raise ValueError(msg)
        # Reject ambiguous URLs without including potentially secret input in errors.
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
