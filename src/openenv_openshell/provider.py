"""OpenEnv provider lifecycle entry point."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from openenv_openshell._compat import ContainerProvider
from openenv_openshell.config import OpenShellProviderConfig
from openenv_openshell.metadata import ProviderState

if TYPE_CHECKING:
    from collections.abc import Mapping

_NOT_IMPLEMENTED = "OpenShell lifecycle is planned for Milestone 1"


class OpenShellProvider(ContainerProvider):
    """Run one OpenEnv environment server in an OpenShell sandbox."""

    def __init__(self, config: OpenShellProviderConfig | None = None) -> None:
        """Create a provider without contacting an OpenShell gateway."""
        self.config = config or OpenShellProviderConfig()
        self.state = ProviderState()

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
