"""Smoke-test installed artifacts' SDK prerequisite without a gateway."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
from traceback import format_exception

from openenv_openshell import OpenShellProvider
from openenv_openshell.errors import OpenShellConnectionError
from openenv_openshell.policy import load_policy


def main() -> None:
    """Exercise explicit policies with and without the separately installed SDK."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", choices=("missing", "installed"), required=True)
    args = parser.parse_args()
    with TemporaryDirectory() as directory:
        path = Path(directory) / "policy.yaml"
        path.write_text("version: 1\n", encoding="utf-8")
        for policy in (None, {"version": 1}, path):
            provider = OpenShellProvider(command=["server"], policy=policy)
            if args.expected == "installed":
                if policy is not None and load_policy(policy) != {"version": 1}:
                    msg = "Pinned SDK policy normalization failed"
                    raise RuntimeError(msg)
            else:
                try:
                    provider.start_container("image")
                except OpenShellConnectionError as error:
                    diagnostic = "".join(format_exception(error))
                    if (
                        "hash-pinned OpenShell 0.1.2 wheel" not in diagnostic
                        or "ModuleNotFoundError" in diagnostic
                    ):
                        msg = "SDK prerequisite error is not actionable and sanitized"
                        raise RuntimeError(msg) from None
                else:
                    msg = "Startup unexpectedly succeeded without the SDK"
                    raise RuntimeError(msg)
            provider.stop_container()


if __name__ == "__main__":
    main()
