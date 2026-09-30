"""Tests for the initial public package boundary."""

from dataclasses import FrozenInstanceError

import pytest

from openenv_openshell import (
    OpenShellProvider,
    OpenShellProviderConfig,
    OpenShellResources,
)
from openenv_openshell._compat import ContainerProvider


def test_provider_is_an_openenv_container_provider() -> None:
    """The reserved public class already satisfies the upstream type boundary."""
    provider = OpenShellProvider()

    assert isinstance(provider, ContainerProvider)
    assert provider.config == OpenShellProviderConfig()
    assert provider.state.created is False


def test_configuration_is_immutable() -> None:
    """Shared configuration cannot be mutated by lifecycle components."""
    config = OpenShellProviderConfig(resources=OpenShellResources(cpu=2.0))

    with pytest.raises(FrozenInstanceError):
        config.workspace = "other"  # pyright: ignore[reportAttributeAccessIssue]


def test_public_cleanup_remains_pending() -> None:
    """The incomplete public cleanup path must fail explicitly until P6."""
    provider = OpenShellProvider()

    with pytest.raises(NotImplementedError, match="Milestone 1"):
        provider.stop_container()
