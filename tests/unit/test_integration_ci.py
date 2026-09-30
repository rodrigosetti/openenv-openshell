"""Offline controls for CI opt-in, false success, and timeout cleanup."""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.integration import _ci


def test_missing_inputs_never_start_runtime() -> None:
    """CI cannot pass by silently skipping an unconfigured runtime."""
    with (
        patch.dict(os.environ, {}, clear=True),
        patch.object(_ci, "run_bounded") as run,
    ):
        assert _ci.main() == _ci.MISCONFIGURED
    run.assert_not_called()


@pytest.mark.parametrize("outcome", ["skipped", "failure", "error"])
def test_report_rejects_false_success(tmp_path: Path, outcome: str) -> None:
    """A zero pytest exit cannot conceal skipped or failed acceptance cases."""
    report = tmp_path / "report.xml"
    report.write_text(
        f"<testsuites><testsuite><testcase><{outcome}/></testcase>"
        "</testsuite></testsuites>"
    )
    assert not _ci.report_passed(report, 1)


def test_report_requires_expected_cases(tmp_path: Path) -> None:
    """All selected acceptance cases must actually run."""
    report = tmp_path / "report.xml"
    report.write_text("<testsuites><testsuite><testcase/></testsuite></testsuites>")
    assert _ci.report_passed(report, 1)
    assert not _ci.report_passed(report, 2)


def test_timeout_allows_child_cleanup(tmp_path: Path) -> None:
    """A real subprocess catches SIGTERM and completes its cleanup before exit."""
    ready = tmp_path / "ready"
    cleaned = tmp_path / "cleaned"
    code = (
        "import pathlib, signal, sys, time\n"
        "def cleanup(signum, frame):\n"
        "    pathlib.Path(sys.argv[2]).touch()\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, cleanup)\n"
        "pathlib.Path(sys.argv[1]).touch()\n"
        "while True: time.sleep(0.01)\n"
    )
    with patch.object(_ci, "SUITE_TIMEOUT_S", 1):
        assert (
            _ci.run_bounded(
                [sys.executable, "-c", code, str(ready), str(cleaned)],
                dict(os.environ),
            )
            == _ci.TIMED_OUT
        )
    assert ready.exists()
    assert cleaned.exists()


def test_unresponsive_child_has_bounded_cleanup(tmp_path: Path) -> None:
    """A child ignoring SIGTERM is reaped after the cleanup grace expires."""
    ready = tmp_path / "ready"
    code = (
        "import pathlib, signal, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "pathlib.Path(sys.argv[1]).touch()\n"
        "while True: time.sleep(0.01)\n"
    )
    with (
        patch.object(_ci, "SUITE_TIMEOUT_S", 1),
        patch.object(_ci, "CLEANUP_GRACE_S", 0.1),
    ):
        assert (
            _ci.run_bounded([sys.executable, "-c", code, str(ready)], dict(os.environ))
            == _ci.TIMED_OUT
        )
    assert ready.exists()
