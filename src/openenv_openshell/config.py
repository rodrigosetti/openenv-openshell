"""Typed configuration for the OpenShell provider."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

Policy: TypeAlias = str | Path | Mapping[str, object] | None

_MAX_NAME_LENGTH = 63
_MAX_LABEL_KEY_LENGTH = 128
_MAX_LABEL_VALUE_LENGTH = 256
_MAX_PORT = 65535
_NAME_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\Z")
_LABEL_KEY_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._/-]*[A-Za-z0-9])?\Z")
_MEMORY_PATTERN = re.compile(r"(?P<amount>\d+(?:\.\d+)?)(?P<unit>[A-Za-z]+)?\Z")
_SENSITIVE_LABEL_TERMS = frozenset(
    {
        "credential",
        "credentials",
        "password",
        "passwd",
        "prompt",
        "secret",
        "token",
        "user-data",
        "user_data",
    }
)
_SENSITIVE_LABEL_PHRASES = ("api-key", "task-content", "user-data")


def _validate_name(value: str, *, field_name: str, allow_empty: bool = False) -> None:
    if allow_empty and not value:
        return
    if not value:
        msg = f"{field_name} must not be empty"
        raise ValueError(msg)
    if len(value) > _MAX_NAME_LENGTH or _NAME_PATTERN.fullmatch(value) is None:
        msg = (
            f"{field_name} must be at most {_MAX_NAME_LENGTH} lowercase letters, "
            "digits, or hyphens, and must start and end with a letter or digit"
        )
        raise ValueError(msg)


def _validate_positive_number(value: float, *, field_name: str) -> None:
    if isinstance(value, bool) or not isfinite(value) or value <= 0:
        msg = f"{field_name} must be a positive finite number"
        raise ValueError(msg)


def _validate_labels(labels: Mapping[str, str]) -> None:
    for key, value in labels.items():
        if not isinstance(key, str) or not isinstance(value, str):  # pyright: ignore[reportUnnecessaryIsInstance]
            msg = "labels must contain only string keys and values"
            raise TypeError(msg)
        if (
            len(key) > _MAX_LABEL_KEY_LENGTH
            or _LABEL_KEY_PATTERN.fullmatch(key) is None
        ):
            msg = f"invalid label key: {key!r}"
            raise ValueError(msg)
        normalized_key = key.casefold().replace("_", "-")
        normalized_parts = set(re.split(r"[-./]", normalized_key))
        if normalized_parts & _SENSITIVE_LABEL_TERMS or any(
            phrase in normalized_key for phrase in _SENSITIVE_LABEL_PHRASES
        ):
            msg = f"label key must not identify sensitive or private data: {key!r}"
            raise ValueError(msg)
        if len(value) > _MAX_LABEL_VALUE_LENGTH or any(
            character.isspace() and character != " " for character in value
        ):
            msg = f"invalid label value for {key!r}"
            raise ValueError(msg)


def validate_command(command: Sequence[str] | None) -> tuple[str, ...]:
    """Require exact argv without exposing command contents in errors."""
    if command is None:
        msg = "OpenShell 0.1.2 requires explicit command argv; configure command"
        raise ValueError(msg)
    if isinstance(command, (str, bytes)) or not isinstance(command, Sequence):  # pyright: ignore[reportUnnecessaryIsInstance] - Validate untyped callers.
        msg = "command must be a non-empty sequence of string arguments"
        raise TypeError(msg)
    argv = tuple(command)
    if (
        not argv
        or any(not isinstance(arg, str) or "\x00" in arg for arg in argv)  # pyright: ignore[reportUnnecessaryIsInstance]
        or not argv[0].strip()
    ):
        msg = "command requires a non-empty executable and NUL-free string arguments"
        raise ValueError(msg)
    return argv


@dataclass(frozen=True, slots=True)
class OpenShellResources:
    """Resource requests passed through to OpenShell."""

    cpu: float | None = None
    memory: str | None = None
    gpu_count: int | None = None

    def __post_init__(self) -> None:
        """Reject resource requests that cannot represent positive capacity."""
        if self.cpu is not None:
            _validate_positive_number(self.cpu, field_name="resources.cpu")
        if self.memory is not None:
            match = _MEMORY_PATTERN.fullmatch(self.memory)
            if match is None or float(match.group("amount")) <= 0:
                msg = "resources.memory must be a positive quantity"
                raise ValueError(msg)
        if self.gpu_count is not None and (
            isinstance(self.gpu_count, bool)
            or not isinstance(self.gpu_count, int)  # pyright: ignore[reportUnnecessaryIsInstance]
            or self.gpu_count <= 0
        ):
            msg = "resources.gpu_count must be a positive integer"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class OpenShellProviderConfig:
    """Immutable provider settings shared by lifecycle components."""

    workspace: str = "default"
    sandbox_name: str | None = None
    policy: Policy = None
    command: Sequence[str] | None = field(default=None, repr=False)
    service_port: int = 8000
    service_name: str = ""
    startup_timeout_s: float = 120.0
    deletion_timeout_s: float = 60.0
    health_poll_interval_s: float = 0.5
    health_request_timeout_s: float = 2.0
    gateway: str | None = None
    keep_sandbox: bool = False
    labels: Mapping[str, str] = field(default_factory=dict[str, str])
    providers: Sequence[str] = field(default_factory=tuple[str, ...])
    resources: OpenShellResources | None = None

    def __post_init__(self) -> None:
        """Validate settings and detach mutable values supplied by callers."""
        if self.command is not None:
            object.__setattr__(self, "command", validate_command(self.command))
        if not self.workspace.strip():
            msg = "workspace must not be empty"
            raise ValueError(msg)
        if self.sandbox_name is not None:
            _validate_name(self.sandbox_name, field_name="sandbox_name")
        _validate_name(self.service_name, field_name="service_name", allow_empty=True)
        if (
            isinstance(self.service_port, bool)
            or not isinstance(self.service_port, int)  # pyright: ignore[reportUnnecessaryIsInstance]
            or self.service_port < 1
            or self.service_port > _MAX_PORT
        ):
            msg = f"service_port must be an integer from 1 through {_MAX_PORT}"
            raise ValueError(msg)
        _validate_positive_number(
            self.startup_timeout_s, field_name="startup_timeout_s"
        )
        _validate_positive_number(
            self.deletion_timeout_s, field_name="deletion_timeout_s"
        )
        _validate_positive_number(
            self.health_poll_interval_s, field_name="health_poll_interval_s"
        )
        _validate_positive_number(
            self.health_request_timeout_s, field_name="health_request_timeout_s"
        )
        if self.gateway is not None and not self.gateway.strip():
            msg = "gateway must not be empty"
            raise ValueError(msg)

        labels = dict(self.labels)
        _validate_labels(labels)
        object.__setattr__(self, "labels", MappingProxyType(labels))

        if isinstance(self.providers, str):
            msg = "providers must be a sequence of provider names"
            raise TypeError(msg)
        providers = tuple(self.providers)
        if any(
            not isinstance(provider, str)  # pyright: ignore[reportUnnecessaryIsInstance]
            or not provider.strip()
            for provider in providers
        ):
            msg = "providers must contain non-empty strings"
            raise ValueError(msg)
        object.__setattr__(self, "providers", providers)

        if isinstance(self.policy, Mapping):
            policy = MappingProxyType(deepcopy(dict(self.policy)))
            object.__setattr__(self, "policy", policy)
