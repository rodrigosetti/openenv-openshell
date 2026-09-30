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


def test_public_cleanup_before_start() -> None:
    """Cleanup before startup is a harmless no-op."""
    provider = OpenShellProvider()

    provider.stop_container()
