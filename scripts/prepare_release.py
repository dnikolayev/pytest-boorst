"""Assemble the explicitly selected, CI-tested release distributions."""

import argparse
import hashlib
import html
import json
import shutil
import tarfile
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import quote
from zipfile import ZipFile

import tomllib

WHEEL_ARTIFACTS = (
    "wheel-macos-14-py3.12",
    "wheel-macos-x86_64",
    "wheel-windows-latest-py3.12",
    "wheel-windows-x86",
    "wheel-windows-arm64",
    "wheel-manylinux-x86_64",
    "wheel-manylinux-aarch64",
    "wheel-manylinux-i686",
    "wheel-musllinux-x86_64",
    "wheel-musllinux-aarch64",
    "wheel-musllinux-i686",
    "wheel-universal",
)


def assemble(artifacts, output, tag, source_commit):
    version = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
    if tag != f"v{version}":
        raise ValueError(
            f"Release tag {tag!r} does not match package version {version}"
        )
    files = []
    for artifact in (*WHEEL_ARTIFACTS, "source-distribution"):
        suffix = "*.tar.gz" if artifact == "source-distribution" else "*.whl"
        matches = list((artifacts / artifact).glob(suffix))
        if len(matches) != 1:
            raise ValueError(
                f"Expected one distribution in {artifact}, got {len(matches)}"
            )
        path = matches[0]
        if not path.name.startswith(f"pytest_boorst-{version}-") and path.name != (
            f"pytest_boorst-{version}.tar.gz"
        ):
            raise ValueError(f"Unexpected distribution: {path.name}")
        if path.suffix == ".whl":
            with ZipFile(path) as wheel:
                metadata_paths = [
                    n for n in wheel.namelist() if n.endswith("/METADATA")
                ]
                if len(metadata_paths) != 1:
                    raise ValueError(f"Expected one metadata file in {path.name}")
                metadata_bytes = wheel.read(metadata_paths[0])
        else:
            with tarfile.open(path, "r:gz") as archive:
                metadata_paths = [
                    member
                    for member in archive.getmembers()
                    if member.name.count("/") == 1
                    and member.name.endswith("/PKG-INFO")
                    and member.isfile()
                ]
                if len(metadata_paths) != 1:
                    raise ValueError(f"Expected one metadata file in {path.name}")
                metadata_bytes = archive.extractfile(metadata_paths[0]).read()
        metadata = BytesParser().parsebytes(metadata_bytes)
        if metadata["Name"] != "pytest-boorst" or metadata["Version"] != version:
            raise ValueError(f"Unexpected package metadata in {path.name}")
        files.append(path)
    if len({path.name for path in files}) != len(files):
        raise ValueError("Selected artifacts contain duplicate distribution filenames")
    if output.exists():
        raise ValueError(f"Output directory already exists: {output}")
    output.mkdir(parents=True)
    records = []
    for path in files:
        shutil.copyfile(path, output / path.name)
        records.append(
            {
                "filename": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    extras = output.parent / "release-evidence"
    extras.mkdir(exist_ok=True)
    (extras / "manifest.json").write_text(
        json.dumps(
            {"version": version, "source_commit": source_commit, "files": records},
            indent=2,
        )
        + "\n"
    )
    links = []
    for record in records:
        if record["filename"].endswith(".whl"):
            url = (
                "https://github.com/dnikolayev/pytest-boorst/releases/download/"
                f"{quote(tag)}/{quote(record['filename'])}#sha256={record['sha256']}"
            )
            links.append(f'<a href="{html.escape(url)}">{record["filename"]}</a><br>')
    (extras / "wheels.html").write_text(
        "<!doctype html>\n<html><body>\n" + "\n".join(links) + "\n</body></html>\n"
    )
    print(f"Prepared {len(records)} tested distributions for {tag}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    assemble(args.artifacts, args.output, args.tag, args.source_commit)


if __name__ == "__main__":
    main()
