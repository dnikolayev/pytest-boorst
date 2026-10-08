"""Verify installed trial behavior against a local release wheel directory."""

import argparse
import subprocess
import sys
import tempfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheels", type=Path, required=True)
    parser.add_argument("--expect-native", action="store_true")
    args = parser.parse_args()
    trial = Path(__file__).with_name("try.py").resolve()
    with tempfile.TemporaryDirectory(prefix="boorst-trial-check-") as temporary:
        root = Path(temporary)
        environment = root / ".venv"
        subprocess.run(
            ["uv", "venv", "--python", sys.executable, str(environment)], check=True
        )
        executable = environment / (
            "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
        )
        subprocess.run(
            ["uv", "pip", "install", "--python", str(executable), "pytest==9.1.1"],
            check=True,
        )
        (root / "test_sample.py").write_text(
            "import pytest\n"
            "@pytest.mark.parametrize('value', range(128), ids=['case'] * 128)\n"
            "def test_pass(value):\n    assert value >= 0\n"
            "def test_fail():\n    assert False, 'expected trial failure'\n",
            encoding="utf-8",
        )
        for group in range(2):
            cases = root / f"cases_{group}"
            cases.mkdir()
            for index in range(32):
                (cases / f"test_{group}_{index:02d}.py").write_text(
                    "def test_case():\n    assert True\n", encoding="utf-8"
                )
        (root / "conftest.py").write_text(
            "import json\nfrom pathlib import Path\nfrom pytest_boorst import plugin\n"
            "def pytest_sessionfinish(session):\n"
            "    state = dict(session.config.stash.get(plugin.STATE_KEY, {}))\n"
            "    Path('state.json').write_text(json.dumps(state))\n",
            encoding="utf-8",
        )
        (root / "pyproject.toml").write_text(
            '[project]\nname = "trial-example"\nversion = "0.0.0"\n'
            'dependencies = ["pytest==9.1.1"]\n',
            encoding="utf-8",
        )
        (root / "uv.lock").write_text("unchanged example lock\n", encoding="utf-8")
        driver = root / "check.py"
        driver.write_text(
            "import importlib.metadata, importlib.util, json, os, subprocess, sys\n"
            "from pathlib import Path\n"
            "assert Path(sys.prefix).resolve() == (Path.cwd() / '.venv').resolve()\n"
            "def versions():\n"
            "    return {d.metadata['Name']: d.version for d in importlib.metadata.distributions()}\n"
            "before = versions()\n"
            "files = {p: Path(p).read_bytes() for p in ['pyproject.toml', 'uv.lock']}\n"
            f"spec = importlib.util.spec_from_file_location('trial', {str(trial)!r})\n"
            "trial = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(trial)\n"
            f"trial.WHEELS = {str(args.wheels.resolve())!r}\n"
            "sys.argv = ['try.py', '-q', 'test_sample.py::test_pass']\n"
            "assert trial.main() == 0\n"
            "after = versions()\n"
            "assert {k: v for k, v in after.items() if k != 'pytest-boorst'} == before\n"
            "assert after['pytest-boorst'] == trial.VERSION\n"
            "import pytest\nassert pytest.__version__ == '9.1.1'\n"
            "assert os.environ['PYTEST_BOORST'] == '1'\n"
            "assert all(Path(p).read_bytes() == data for p, data in files.items())\n"
            f"assert ('pytest_boorst._native' in sys.modules) is {args.expect_native!r}\n"
            "sys.argv = ['try.py', '-q', *[f'cases_{g}/test_{g}_{i:02d}.py' for i in range(32) for g in range(2)]]\n"
            "assert trial.main() == 0\n"
            "state = json.loads(Path('state.json').read_text())\n"
            "assert state.get('directory_reuses', 0) == (0 if sys.platform == 'win32' else 62)\n"
            "sys.argv = ['try.py', '-q', 'test_sample.py::test_fail']\n"
            "assert trial.main() == 1\n"
            "env = os.environ.copy()\n"
            "env.pop('PYTEST_BOORST', None)\n"
            "command = ['uv', 'run', '--no-sync', 'python', '-m', 'pytest_boorst']\n"
            "paths = [f'cases_{g}/test_{g}_{i:02d}.py' for i in range(32) for g in range(2)]\n"
            "assert subprocess.run(command + ['-q', '-W', 'error::pytest.PytestAssertRewriteWarning', 'test_sample.py::test_pass'], env=env).returncode == 0\n"
            "state = json.loads(Path('state.json').read_text())\n"
            f"assert state.get('native_calls', 0) == int({args.expect_native!r})\n"
            "assert subprocess.run(command + ['-q', *paths], env=env).returncode == 0\n"
            "state = json.loads(Path('state.json').read_text())\n"
            "assert state.get('directory_reuses', 0) == (0 if sys.platform == 'win32' else 62)\n"
            "assert subprocess.run(command + ['-q', 'test_sample.py::test_fail'], env=env).returncode == 1\n"
            "assert subprocess.run(command + ['-q', '-p', 'no:boorst', 'test_sample.py::test_pass'], env=env).returncode == 0\n"
            "assert json.loads(Path('state.json').read_text()) == {}\n"
            "command = ['uv', 'run', '--no-sync', 'pytest', '--boorst']\n"
            "assert subprocess.run(command + ['-q', '-W', 'error::pytest.PytestAssertRewriteWarning', 'test_sample.py::test_pass'], env=env).returncode == 0\n"
            "state = json.loads(Path('state.json').read_text())\n"
            f"assert state.get('native_calls', 0) == int({args.expect_native!r})\n"
            "assert subprocess.run(command + ['-q', *paths], env=env).returncode == 0\n"
            "state = json.loads(Path('state.json').read_text())\n"
            "assert state.get('directory_reuses', 0) == (0 if sys.platform == 'win32' else 62)\n"
            "assert subprocess.run(command + ['-q', 'test_sample.py::test_fail'], env=env).returncode == 1\n"
            "assert subprocess.run(['uv', 'run', '--no-sync', 'pytest', '-q', 'test_sample.py::test_pass'], env=env).returncode == 0\n"
            "assert json.loads(Path('state.json').read_text())['status'] == 'disabled'\n"
            "manual_env = dict(env, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')\n"
            "assert subprocess.run(command + ['-p', 'boorst', '-q', 'test_sample.py::test_pass'], env=manual_env).returncode == 0\n"
            "state = json.loads(Path('state.json').read_text())\n"
            f"assert state.get('native_calls', 0) == int({args.expect_native!r})\n"
            "assert versions() == after\n"
            "assert all(Path(p).read_bytes() == data for p, data in files.items())\n"
            "print('Trial, module and pytest option verified: arguments, exit status, opt-in/out, unchanged dependencies/configuration')\n",
            encoding="utf-8",
        )
        handler = partial(SimpleHTTPRequestHandler, directory=str(root))
        with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                subprocess.run(
                    [
                        "uv",
                        "run",
                        "--no-sync",
                        f"http://127.0.0.1:{server.server_port}/check.py",
                    ],
                    cwd=root,
                    check=True,
                    timeout=120,
                )
            finally:
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    main()
