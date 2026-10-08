"""Release assembly must select tested files without overwriting ABI3 builds."""

import hashlib
import importlib.util
import io
import json
import tarfile
from pathlib import Path
from zipfile import ZipFile

import pytest

pytest.importorskip("tomllib", reason="Release assembly runs on Python 3.12")
SPEC = importlib.util.spec_from_file_location(
    "prepare_release",
    Path(__file__).resolve().parents[1] / "scripts/prepare_release.py",
)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def write_source(path, version="0.1.0a5"):
    metadata = f"Name: pytest-boorst\nVersion: {version}\n".encode()
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo("pytest_boorst-0.1.0a5/PKG-INFO")
        member.size = len(metadata)
        archive.addfile(member, io.BytesIO(metadata))


@pytest.fixture
def artifacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.1.0a5"\n')
    root = tmp_path / "artifacts"
    for index, artifact in enumerate(release.WHEEL_ARTIFACTS):
        directory = root / artifact
        directory.mkdir(parents=True)
        path = directory / f"pytest_boorst-0.1.0a5-cp310-abi3-platform{index}.whl"
        with ZipFile(path, "w") as wheel:
            wheel.writestr(
                "pytest_boorst-0.1.0a5.dist-info/METADATA",
                "Name: pytest-boorst\nVersion: 0.1.0a5\n",
            )
    source = root / "source-distribution"
    source.mkdir()
    write_source(source / "pytest_boorst-0.1.0a5.tar.gz")
    return root


def test_release_selects_canonical_files_and_binds_checksums(artifacts, tmp_path):
    # Compatibility lanes can produce duplicate ABI3 filenames; ignore those lanes.
    other = artifacts / "wheel-ubuntu-24.04-py3.12"
    other.mkdir()
    (other / "pytest_boorst-0.1.0a5-cp310-abi3-platform0.whl").write_bytes(
        b"unselected"
    )
    output = tmp_path / "dist"
    release.assemble(artifacts, output, "v0.1.0a5", "a" * 40)
    manifest = json.loads((tmp_path / "release-evidence/manifest.json").read_text())
    assert manifest["source_commit"] == "a" * 40
    assert manifest["version"] == "0.1.0a5"
    assert len(list(output.iterdir())) == len(manifest["files"]) == 13
    index = (tmp_path / "release-evidence/wheels.html").read_text()
    for record in manifest["files"]:
        path = output / record["filename"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
        if path.suffix == ".whl":
            assert f"{path.name}#sha256={record['sha256']}" in index


def test_missing_platform_stops_before_copying(artifacts, tmp_path):
    next((artifacts / release.WHEEL_ARTIFACTS[0]).iterdir()).unlink()
    with pytest.raises(ValueError, match="Expected one distribution"):
        release.assemble(artifacts, tmp_path / "dist", "v0.1.0a5", "a" * 40)
    assert not (tmp_path / "dist").exists()


def test_duplicate_filenames_stop_before_overwriting(artifacts, tmp_path):
    first = next((artifacts / release.WHEEL_ARTIFACTS[0]).iterdir())
    second = next((artifacts / release.WHEEL_ARTIFACTS[1]).iterdir())
    second.rename(second.with_name(first.name))
    with pytest.raises(ValueError, match="duplicate distribution filenames"):
        release.assemble(artifacts, tmp_path / "dist", "v0.1.0a5", "a" * 40)
    assert not (tmp_path / "dist").exists()


@pytest.mark.parametrize(
    "metadata",
    ["Name: different\nVersion: 0.1.0a5\n", "Name: pytest-boorst\nVersion: 0.1.0a4\n"],
)
def test_wrong_package_metadata_is_rejected(artifacts, tmp_path, metadata):
    path = next((artifacts / release.WHEEL_ARTIFACTS[0]).iterdir())
    with ZipFile(path, "w") as wheel:
        wheel.writestr("pytest_boorst-0.1.0a5.dist-info/METADATA", metadata)
    with pytest.raises(ValueError, match="Unexpected package metadata"):
        release.assemble(artifacts, tmp_path / "dist", "v0.1.0a5", "a" * 40)
    assert not (tmp_path / "dist").exists()


def test_wrong_tag_is_rejected(artifacts, tmp_path):
    with pytest.raises(ValueError, match="does not match package version"):
        release.assemble(artifacts, tmp_path / "dist", "v0.1.0a4", "a" * 40)
    assert not (tmp_path / "dist").exists()


def test_stale_source_metadata_is_rejected(artifacts, tmp_path):
    path = artifacts / "source-distribution/pytest_boorst-0.1.0a5.tar.gz"
    write_source(path, version="0.1.0a4")
    with pytest.raises(ValueError, match="Unexpected package metadata"):
        release.assemble(artifacts, tmp_path / "dist", "v0.1.0a5", "a" * 40)
    assert not (tmp_path / "dist").exists()


def test_corrupt_source_is_rejected(artifacts, tmp_path):
    path = artifacts / "source-distribution/pytest_boorst-0.1.0a5.tar.gz"
    path.write_bytes(b"invalid archive")
    with pytest.raises(tarfile.ReadError):
        release.assemble(artifacts, tmp_path / "dist", "v0.1.0a5", "a" * 40)
    assert not (tmp_path / "dist").exists()
