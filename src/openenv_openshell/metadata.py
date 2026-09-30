"""Lifecycle state and audit metadata models."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(slots=True)
class ProviderState:
    """Mutable state for the provider's single owned sandbox."""

    sandbox_name: str | None = None
    sandbox_id: str | None = None
    image: str | None = None
    base_url: str | None = None
    created: bool = False
    ready: bool = False
    deleted: bool = False


@dataclass(frozen=True, slots=True)
class OpenShellRunMetadata:
    """Non-secret provenance for one OpenEnv run."""

    sandbox_name: str
    sandbox_id: str | None
    workspace: str
    image: str
    service_url: str
    policy_digest: str | None
    created_at: datetime

    openenv_provider_version: str | None = None
    openshell_version: str | None = None
    openenv_version: str | None = None
    ready_at: datetime | None = None
    deleted_at: datetime | None = None


def package_version(distribution: str) -> str | None:
    """Read installed distribution provenance without importing runtime SDKs."""
    try:
        return version(distribution)
    except PackageNotFoundError:
        return None
