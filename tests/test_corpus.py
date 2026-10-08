import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "boorst_corpus", Path(__file__).resolve().parents[1] / "benchmarks/corpus.py"
)
corpus = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(corpus)


@pytest.mark.parametrize("mismatch", [False, True])
def test_alternating_samples_bind_parity_and_keep_profile_untimed(
    tmp_path, monkeypatch, mismatch
):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    calls = []
    base_python = tmp_path / "base-python"
    base_python.touch()
    python = tmp_path / "venv-python"
    try:
        python.symlink_to(base_python)
    except OSError:
        pytest.skip("symbolic links unavailable")

    def metadata(command, **kwargs):
        if command[0] == "git":
            return "a" * 40 if "rev-parse" in command else ""
        assert command[0] == str(python)
        return json.dumps({"python": "example", "versions": {"pytest": "9.1.1"}})

    def run(command, **kwargs):
        assert command[0] == str(python)
        assert kwargs["cwd"] == checkout
        assert kwargs["env"]["PYTEST_BOORST"] == "0"
        if "--help" in command:
            return SimpleNamespace(returncode=0, stdout="--boorst-profile", stderr="")
        mode = "enabled" if "--boorst" in command else "stock"
        profile = "--boorst-profile" in command
        calls.append("profile" if profile else mode)
        nodes = ["test_example.py::test_first", "test_example.py::test_second"]
        if mismatch and mode == "enabled":
            nodes.reverse()
        Path(kwargs["env"]["BOORST_CORPUS_RECEIPT"]).write_text(
            json.dumps(
                {
                    "nodes": nodes,
                    "errors": [],
                    "exitstatus": 0,
                    "state": {"native_calls": 1} if mode == "enabled" else None,
                    "profile": {"collection_wall": 0.5} if profile else None,
                }
            )
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(corpus.subprocess, "check_output", metadata)
    monkeypatch.setattr(corpus.subprocess, "run", run)
    output = tmp_path / "private.json"
    if mismatch:
        with pytest.raises(AssertionError, match="parity failed"):
            corpus.compare(checkout, python, ["tests"], output)
    else:
        corpus.compare(checkout, python, ["tests"], output)
    result = json.loads(output.read_text())
    assert calls == [
        "stock",
        "enabled",
        "enabled",
        "stock",
        "stock",
        "enabled",
        "profile",
    ]
    assert result["parity"] is not mismatch
    assert len(result["samples"]) == 6
    assert result["profile_run"]["profile"]["collection_wall"] == 0.5
    assert result["collected_count"] == 2
    assert result["ordered_ids_sha256"] == corpus.digest(result["samples"][0]["nodes"])


def test_audit_records_partial_collection_and_errors(pytester, monkeypatch):
    pytester.makepyfile(
        boorst_corpus_audit=corpus.AUDIT,
        test_ok="def test_example():\n    pass\n",
        test_broken="raise RuntimeError('example collection failure')",
    )
    receipt = pytester.path / "private.json"
    monkeypatch.setenv("BOORST_CORPUS_RECEIPT", str(receipt))
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    monkeypatch.setenv("PYTHONPATH", str(pytester.path))
    result = pytester.runpytest_subprocess(
        "-q", "--collect-only", "-p", "boorst_corpus_audit", "-p", "no:boorst"
    )
    data = json.loads(receipt.read_text())
    assert result.ret == data["exitstatus"] == 2
    assert data["nodes"] == ["test_ok.py::test_example"]
    assert data["errors"][0][0] == "test_broken.py"
    assert "example collection failure" in data["errors"][0][1]
    assert data["state"] is None and data["profile"] is None
