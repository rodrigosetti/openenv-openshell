"""Fail-closed loading of explicit policies without gateway access."""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, cast

import yaml

from openenv_openshell.errors import PolicyConfigurationError

_INVALID = "Invalid explicit policy; use supported OpenShell 0.1.2 policy fields."
_MAX_BYTES = 1024 * 1024
_MAX_DEPTH = 64

if TYPE_CHECKING:
    from collections.abc import Hashable, Iterator

    from yaml.events import Event
    from yaml.nodes import MappingNode


def policy_digest(policy: Mapping[str, object]) -> str:
    """Hash normalized SDK fields as sorted, compact UTF-8 JSON.

    Preserve list order; only mapping order and authored schema spellings are
    normalized. The caller must pass the validated output of load_policy.
    """
    canonical = json.dumps(
        dict(policy), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


class _PolicyLoader(yaml.SafeLoader):
    """Reject duplicate keys and merge keys instead of silently overriding."""

    def construct_mapping(
        self,
        node: MappingNode,
        deep: bool = False,  # noqa: FBT001, FBT002 - PyYAML override.
    ) -> dict[Hashable, object]:
        keys: set[str] = set()
        for key_node, _ in node.value:
            key: object = self.construct_object(key_node, deep=deep)  # pyright: ignore[reportUnknownMemberType] - PyYAML stub lacks node type.
            if not isinstance(key, str) or key in keys or key == "<<":
                raise PolicyConfigurationError(_INVALID)
            keys.add(key)
        return cast("dict[Hashable, object]", super().construct_mapping(node, deep))


def _detach(value: object, depth: int = 0) -> object:
    if depth > _MAX_DEPTH:
        raise PolicyConfigurationError(_INVALID)
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, child in cast("Mapping[object, object]", value).items():
            if not isinstance(key, str):
                raise PolicyConfigurationError(_INVALID)
            result[key] = _detach(child, depth + 1)
        return dict(sorted(result.items()))
    if isinstance(value, list):
        return [_detach(child, depth + 1) for child in cast("list[object]", value)]
    if isinstance(value, (str, bool, int)):
        return value
    raise PolicyConfigurationError(_INVALID)


def load_policy(source: object) -> dict[str, object]:
    """Load a YAML path or mapping and return detached normalized SDK fields.

    None is not an explicit policy. Image/default policy selection belongs to
    the caller and must never be used to recover from an explicit-policy error.
    """
    try:
        if isinstance(source, (str, Path)):
            with Path(source).open("rb") as stream:
                data = stream.read(_MAX_BYTES + 1)
            if len(data) > _MAX_BYTES:
                raise PolicyConfigurationError(_INVALID)
            # Reject aliases/anchors: no recursive or exponentially expanded YAML.
            events = cast("Iterator[Event]", yaml.parse(data))  # pyright: ignore[reportUnknownMemberType] - PyYAML parse return is untyped.
            for event in events:
                if getattr(event, "anchor", None) is not None:
                    raise PolicyConfigurationError(_INVALID)
            source = yaml.load(data, Loader=_PolicyLoader)  # noqa: S506 - SafeLoader subclass.
        detached = _detach(source)
        if not isinstance(detached, dict):
            raise PolicyConfigurationError(_INVALID)
        policy = cast("dict[str, object]", detached)
        if type(policy.get("version")) is not int or policy["version"] != 1:
            raise PolicyConfigurationError(_INVALID)
        if "filesystem_policy" in policy:
            if "filesystem" in policy:
                raise PolicyConfigurationError(_INVALID)
            policy["filesystem"] = policy.pop("filesystem_policy")
        from openenv_openshell._sdk import (  # noqa: PLC0415 - Private lazy model boundary.
            normalize_policy,
        )

        return cast("dict[str, object]", _detach(normalize_policy(policy)))
    except (OSError, UnicodeError, yaml.YAMLError, RecursionError):
        raise PolicyConfigurationError(_INVALID) from None
