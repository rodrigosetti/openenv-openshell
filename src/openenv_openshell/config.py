"""Typed configuration for the OpenShell provider."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeAlias

Policy: TypeAlias = str | Path | Mapping[str, object] | None


@dataclass(frozen=True, slots=True)
class OpenShellResources:
    """Resource requests passed through to OpenShell."""

    cpu: float | None = None
    memory: str | None = None
    gpu_count: int | None = None


@dataclass(frozen=True, slots=True)
class OpenShellProviderConfig:
    """Immutable provider settings shared by lifecycle components."""

    workspace: str = "default"
    sandbox_name: str | None = None
    policy: Policy = None
    service_port: int = 8000
    service_name: str = ""
    startup_timeout_s: float = 120.0
    deletion_timeout_s: float = 60.0
    gateway: str | None = None
    keep_sandbox: bool = False
    labels: Mapping[str, str] = field(default_factory=dict[str, str])
    providers: Sequence[str] = field(default_factory=tuple[str, ...])
    resources: OpenShellResources | None = None
