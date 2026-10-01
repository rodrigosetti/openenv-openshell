"""I9: the README quickstart shows exactly the tested example script."""

import re
from pathlib import Path

from openenv_openshell.policy import load_policy

_ROOT = Path(__file__).parents[2]


def test_readme_quickstart_matches_example_script() -> None:
    """The copy-paste block equals the script body after its header comments."""
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(
        r"\[`examples/quickstart\.py`\]\(examples/quickstart\.py\) is the whole "
        r"program:\n\n```python\n(.*?)```",
        readme,
        re.DOTALL,
    )
    assert match is not None
    script = (_ROOT / "examples/quickstart.py").read_text(encoding="utf-8")
    body = script[script.index("import os\n") :]
    assert match.group(1) == body


def test_quickstart_policy_validates_offline() -> None:
    """The policy referenced by the quickstart loads without a gateway."""
    assert load_policy(_ROOT / "examples/policies/image-compatible.yaml")
