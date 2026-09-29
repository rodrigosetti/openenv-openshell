"""OpenEnv provider lifecycle entry point."""

from __future__ import annotations

import re
import secrets
from typing import TYPE_CHECKING, Any

from openenv_openshell._compat import ContainerProvider
from openenv_openshell.config import (
    OpenShellProviderConfig,
    OpenShellResources,
    Policy,
)
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
        raise NotImplementedError(_NOT_IMPLEMENTED)
