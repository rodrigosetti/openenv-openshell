"""Imports that isolate this package from changes in upstream OpenEnv."""

from openenv.core.containers.runtime.providers import (  # pyright: ignore[reportMissingTypeStubs]
    ContainerProvider,
)

__all__ = ["ContainerProvider"]
