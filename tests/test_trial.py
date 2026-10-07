import importlib.metadata
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "boorst_trial", Path(__file__).resolve().parents[1] / "scripts" / "try.py"
)
trial = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trial)


def prepare(monkeypatch, *, installed=None, exit_code=0):
    monkeypatch.setattr(trial.sys, "prefix", "test-venv")
    monkeypatch.setattr(trial.sys, "base_prefix", "base-python")
    monkeypatch.setattr(trial.importlib.util, "find_spec", lambda name: object())

    def version(name):
        if installed is None:
            raise importlib.metadata.PackageNotFoundError(name)
        return installed

    monkeypatch.setattr(trial.importlib.metadata, "version", version)
    arguments = []
    monkeypatch.setitem(
        sys.modules,
        "pytest",
        SimpleNamespace(main=lambda args: arguments.extend(args) or exit_code),
    )
    monkeypatch.setattr(trial.sys, "argv", ["try.py", "-q", "tests/example.py"])
    monkeypatch.delenv("PYTEST_BOORST", raising=False)
    return arguments


def test_trial_installs_only_boorst_and_forwards_arguments(monkeypatch):
    arguments = prepare(monkeypatch, exit_code=1)
    installs = []
    monkeypatch.setattr(
        trial.subprocess, "run", lambda command, **kw: installs.append((command, kw))
    )
    assert trial.main() == 1
    assert arguments == ["-q", "tests/example.py"]
    assert trial.os.environ["PYTEST_BOORST"] == "1"
    assert installs == [
        (
            [
                "uv",
                "pip",
                "install",
                "--python",
                sys.executable,
                "--no-deps",
                "--only-binary",
                ":all:",
                "--no-index",
                "--find-links",
                trial.WHEELS,
                f"pytest-boorst=={trial.VERSION}",
            ],
            {"check": True},
        )
    ]


def test_installed_alpha_needs_no_network_or_reinstallation(monkeypatch):
    prepare(monkeypatch, installed=trial.VERSION)

    def unexpected(*args, **kwargs):
        pytest.fail("An installed alpha must not invoke the installer.")

    monkeypatch.setattr(trial.subprocess, "run", unexpected)
    assert trial.main() == 0


@pytest.mark.parametrize("missing", ["venv", "pytest"])
def test_missing_environment_fails_before_installation(monkeypatch, missing):
    prepare(monkeypatch)
    if missing == "venv":
        monkeypatch.setattr(trial.sys, "prefix", trial.sys.base_prefix)
    else:
        monkeypatch.setattr(trial.importlib.util, "find_spec", lambda name: None)

    def unexpected(*args, **kwargs):
        pytest.fail("A missing test environment must not invoke the installer.")

    monkeypatch.setattr(trial.subprocess, "run", unexpected)
    with pytest.raises(SystemExit, match="environment|dependencies"):
        trial.main()
    assert "PYTEST_BOORST" not in trial.os.environ


def test_install_failure_does_not_run_pytest(monkeypatch):
    arguments = prepare(monkeypatch)

    def fail_install(*args, **kwargs):
        raise trial.subprocess.CalledProcessError(2, args[0])

    monkeypatch.setattr(trial.subprocess, "run", fail_install)
    with pytest.raises(trial.subprocess.CalledProcessError):
        trial.main()
    assert arguments == []
    assert "PYTEST_BOORST" not in trial.os.environ


def test_trial_has_no_inline_environment_metadata():
    assert "# /// script" not in Path(trial.__file__).read_text(encoding="utf-8")
