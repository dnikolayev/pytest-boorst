"""Build a universal fallback wheel with the standard uv build backend."""

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("dist/pure"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    _, separator, metadata = (
        (root / "pyproject.toml").read_text(encoding="utf-8").partition("\n[project]\n")
    )
    if not separator:
        raise SystemExit("Project metadata is missing.")
    with tempfile.TemporaryDirectory(prefix="boorst-pure-build-") as temporary:
        stage = Path(temporary)
        (stage / "pyproject.toml").write_text(
            '[build-system]\nrequires = ["uv_build>=0.12.12,<0.13"]\n'
            'build-backend = "uv_build"\n\n[project]\n'
            + metadata
            + '\n[tool.uv.build-backend]\nmodule-root = "python"\n',
            encoding="utf-8",
        )
        shutil.copytree(
            root / "python",
            stage / "python",
            ignore=shutil.ignore_patterns("__pycache__", "*.so", "*.pyd", "*.dll"),
        )
        for filename in ("README.md", "LICENSE"):
            shutil.copy2(root / filename, stage / filename)
        subprocess.run(
            [
                "uv",
                "build",
                str(stage),
                "--wheel",
                "--out-dir",
                str(args.out.resolve()),
            ],
            check=True,
        )


if __name__ == "__main__":
    main()
