import json
import sys

import pytest

ELIGIBLE = pytest.__version__ == "9.1.1" and sys.platform != "win32"
OBSERVER = """
import json
from pathlib import Path
import pytest
import app
nodes, reports, events, calls = [], [], [], []
def pytest_configure(config):
    app.config = config
@pytest.fixture
def answer(request):
    events.append([request.node.nodeid, "setup"])
    yield app.answer()
    events.append([request.node.nodeid, "teardown"])
def pytest_collection_finish(session):
    nodes.extend(item.nodeid for item in session.items)
def pytest_runtest_logreport(report):
    reports.append([report.nodeid, report.when, report.outcome,
                    getattr(report, "wasxfail", None)])
def pytest_sessionfinish(session, exitstatus):
    plugin = session.config.pluginmanager.get_plugin("boorst")
    state = dict(session.config.stash[plugin.STATE_KEY]) if plugin else None
    Path("receipt.json").write_text(json.dumps(dict(nodes=nodes, reports=reports,
        events=events, calls=calls, exitstatus=int(exitstatus), state=state)))
"""


def plan(pytester, *, source="", hook="", package=False):
    pytester.makeini("[pytest]")
    pytester.makepyfile(app="def answer():\n    return 42\n")
    pytester.makeconftest(OBSERVER + "\n" + hook)
    directory = pytester.path / "tests"
    directory.mkdir()
    if package:
        (directory / "__init__.py").write_text("")
    paths = [f"tests/test_{number:04}.py" for number in range(32)]
    for path in paths:
        (pytester.path / path).write_text(
            "def test_answer(answer):\n    assert answer == 42\n"
        )
    with (pytester.path / paths[0]).open("a") as stream:
        stream.write("\n" + source)
    return paths


def compare(pytester, monkeypatch, paths, *options, between=lambda: None):
    receipts = []
    for enabled in (False, True):
        (pytester.path / "receipt.json").unlink(missing_ok=True)
        monkeypatch.setenv("PYTEST_BOORST", "1" if enabled else "0")
        monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
        block = [] if enabled else ["-p", "no:boorst"]
        result = pytester.runpytest_subprocess("-q", *block, *options, *paths)
        receipt = json.loads((pytester.path / "receipt.json").read_text())
        assert int(result.ret) == receipt["exitstatus"]
        receipts.append(receipt)
        if not enabled:
            between()
    state = receipts[1].pop("state")
    receipts[0].pop("state")
    assert receipts[0] == receipts[1]
    return state, receipts[1]


@pytest.mark.skipif(
    not ELIGIBLE, reason="directory adapter requires POSIX pytest 9.1.1"
)
@pytest.mark.parametrize("package", [False, True])
def test_directory_outcomes_fixtures_plugins_and_native_ids(
    pytester, monkeypatch, package
):
    paths = plan(
        pytester,
        package=package,
        source="""
import pytest
@pytest.mark.parametrize("value", range(64), ids=["case"] * 64)
def test_parameter(value, answer):
    assert value >= 0 and answer == 42
@pytest.mark.asyncio
async def test_async(answer):
    assert answer == 42
def test_failure(answer):
    assert answer == 0
@pytest.mark.skip(reason="example")
def test_skip():
    pass
@pytest.mark.xfail(reason="example")
def test_xfail(answer):
    assert False
""",
    )
    covered = []
    state, receipt = compare(
        pytester,
        monkeypatch,
        paths,
        "--cov=app",
        "--cov-report=json:coverage.json",
        between=lambda: covered.append(
            json.loads((pytester.path / "coverage.json").read_text())["files"]
        ),
    )
    assert (
        json.loads((pytester.path / "coverage.json").read_text())["files"] == covered[0]
    )
    assert len(receipt["nodes"]) == 100
    assert receipt["exitstatus"] == 1
    assert state["discovery_status"] == "active"
    assert state["directory_reuses"] == 31
    assert state["native_calls"] == 1


@pytest.mark.parametrize("control", ["duplicate", "selector", "lastfailed", "method"])
def test_unsupported_plans_preserve_stock_behavior(pytester, monkeypatch, control):
    hook = (
        """
def pytest_sessionstart(session):
    from _pytest.main import Session
    original = Session._collect_one_node
    def changed(self, node, handle_dupes=True):
        return original(self, node, handle_dupes)
    Session._collect_one_node = changed
"""
        if control == "method"
        else ""
    )
    paths = plan(pytester, hook=hook)
    options = []
    if control == "duplicate":
        paths.append(paths[0])
    elif control == "selector":
        paths[0] += "::test_answer"
    elif control == "lastfailed":
        options = ["--lf", "--cache-clear"]
    state, _ = compare(pytester, monkeypatch, paths, *options)
    assert state.get("directory_reuses", 0) == 0
    if ELIGIBLE:
        assert state["discovery_status"] == "fallback"


@pytest.mark.parametrize("hook", ["pytest_collect_file", "pytest_collectreport"])
def test_custom_collection_hooks_keep_call_order_and_counts(
    pytester, monkeypatch, hook
):
    source = (
        "def pytest_collect_file(file_path, parent):\n"
        "    calls.append(file_path.name)\n"
        if hook == "pytest_collect_file"
        else "def pytest_collectreport(report):\n"
        "    calls.append([report.nodeid, report.outcome])\n"
    )
    state, receipt = compare(pytester, monkeypatch, plan(pytester, hook=source))
    assert receipt["calls"]
    assert state.get("directory_reuses", 0) == 0


@pytest.mark.skipif(
    not ELIGIBLE, reason="directory adapter requires POSIX pytest 9.1.1"
)
@pytest.mark.parametrize(
    "mutation", ["options", "plugins", "directory", "plan", "method"]
)
def test_runtime_changes_invalidate_cached_reports(pytester, monkeypatch, mutation):
    source = {
        "options": "session.config.option.ignore_glob = ['*never-match*']",
        "plugins": "session.config.pluginmanager.register(object(), 'example')",
        "directory": "(directory / 'extra.txt').rename(directory / 'renamed.txt')",
        "plan": "session._collection_cache = {}; "
        "session._initial_parts = session._initial_parts[:1]",
        "method": "from _pytest.main import Session\n"
        "    original = Session._collect_one_node\n"
        "    def changed(self, node, handle_dupes=True):\n"
        "        calls.append(node.nodeid)\n"
        "        return original(self, node, handle_dupes)\n"
        "    Session._collect_one_node = changed",
    }[mutation]
    paths = plan(
        pytester,
        hook=f"""
@pytest.hookimpl(wrapper=True)
def pytest_sessionstart(session):
    yield
    from _pytest.main import Dir, resolve_collection_argument
    session._initial_parts = [resolve_collection_argument(
        session.config.invocation_params.dir, arg, index, as_pypath=False)
        for index, arg in enumerate(session.config.args)]
    directory = Path.cwd() / "tests"
    node = Dir.from_parent(session, path=directory)
    first, _ = session._collect_one_node(node, False)
    {source}
    second, _ = session._collect_one_node(node, False)
    assert first is not second
""",
    )
    directory = pytester.path / "tests"
    (directory / "extra.txt").write_text("example")

    def reset():
        if mutation == "directory":
            (directory / "renamed.txt").rename(directory / "extra.txt")

    state, _ = compare(pytester, monkeypatch, paths, between=reset)
    if mutation == "directory":
        assert state["discovery_status"] == "active"
        assert state["directory_reuses"] == 31
    else:
        assert state["discovery_status"] == "fallback"
        assert state["directory_reuses"] == 0


@pytest.mark.skipif(
    not ELIGIBLE, reason="directory adapter requires POSIX pytest 9.1.1"
)
def test_repeated_main_restores_session_method(pytester):
    paths = plan(pytester)
    script = pytester.makepyfile(
        check=f"""
import os
import pytest
sessions = []
class Observe:
    def pytest_sessionfinish(self, session):
        sessions.append(session)
for enabled in ("1", "0", "1"):
    os.environ["PYTEST_BOORST"] = enabled
    assert pytest.main(["-q", *{paths!r}], plugins=[Observe()]) == 0
    assert "_collect_one_node" not in sessions[-1].__dict__
"""
    )
    result = pytester.runpython(script)
    assert result.ret == 0, result.stdout.str() + result.stderr.str()
