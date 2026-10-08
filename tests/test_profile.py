import json
from types import SimpleNamespace

from pytest_boorst import _profile


def test_worker_totals_replace_repeated_snapshots_and_preserve_controller_reports():
    profiler = _profile.Profiler(SimpleNamespace())
    node = SimpleNamespace(
        gateway=SimpleNamespace(id="gw0"),
        workeroutput={
            "boorst_profile": {
                "modules": {"test_example.py": 2.0},
                "collection_wall": 3.0,
            }
        },
    )
    profiler.reports["call"] = 5.0
    profiler.pytest_testnodedown(node, None)
    profiler.pytest_testnodedown(node, None)
    data = profiler.snapshot()
    assert data["modules"] == {"test_example.py": 2.0}
    assert data["worker_collection_sum"] == 3.0
    assert data["reported_phase_sum"]["call"] == 5.0


def test_profile_preserves_outcomes_and_does_not_enable_acceleration(
    pytester, monkeypatch
):
    monkeypatch.delenv("PYTEST_BOORST", raising=False)
    pytester.makeconftest("""
        import json
        from pathlib import Path
        import pytest
        @pytest.fixture(scope="session")
        def service():
            yield 17
        @pytest.hookimpl(trylast=True)
        def pytest_sessionfinish(session, exitstatus):
            observer = session.config.pluginmanager.get_plugin("boorst_profile")
            boorst = session.config.pluginmanager.get_plugin("boorst")
            Path("profile.json").write_text(json.dumps({
                "data": observer.snapshot() if observer else None,
                "state": session.config.stash[boorst.STATE_KEY],
                "exitstatus": int(exitstatus),
            }))
    """)
    pytester.makepyfile("""
        import pytest
        class TestGroup:
            def test_ok(self, service):
                assert service == 17
        @pytest.mark.skip(reason="example")
        def test_skip():
            pass
        @pytest.mark.xfail(reason="example", strict=True)
        def test_expected_failure(service):
            assert service == 0
    """)
    stock = pytester.runpytest_subprocess("-q")
    active = pytester.runpytest_subprocess("-q", "--boorst-profile")
    stock.assert_outcomes(passed=1, skipped=1, xfailed=1)
    active.assert_outcomes(passed=1, skipped=1, xfailed=1)
    assert active.ret == stock.ret
    active.stdout.fnmatch_lines(["*boorst profile*", "*Startup imports precede*"])
    result = json.loads((pytester.path / "profile.json").read_text())
    assert result["state"]["status"] == "disabled"
    assert result["state"]["native_calls"] == 0
    data = result["data"]
    assert data["collection_wall"] > 0
    assert data["test_loop_wall"] > 0
    assert set(data["reported_phase_sum"]) == {"setup", "call", "teardown"}
    assert all(value > 0 for value in data["reported_phase_sum"].values())
    assert list(data["modules"]) == [
        "test_profile_preserves_outcomes_and_does_not_enable_acceleration.py"
    ]


def test_profile_xdist_reports_worker_collection_and_controller_wall(pytester):
    pytester.makepyfile("""
        import pytest
        @pytest.mark.parametrize("value", range(8))
        def test_example(value):
            assert value >= 0
    """)
    result = pytester.runpytest_subprocess("-q", "--boorst-profile", "-n", "2")
    result.assert_outcomes(passed=8)
    result.stdout.fnmatch_lines(
        ["*Worker collection seconds (sum)*", "*Top module collection seconds*"]
    )


def test_profile_collection_error_remains_an_error(pytester):
    pytester.makepyfile("raise RuntimeError('collection example')")
    result = pytester.runpytest_subprocess("-q", "--boorst-profile")
    assert result.ret == 2
    result.stdout.fnmatch_lines(
        ["*RuntimeError: collection example*", "*boorst profile*"]
    )


def test_profile_keeps_guarded_directory_reuse(pytester):
    import sys

    import pytest

    if pytest.__version__ != "9.1.1" or sys.platform == "win32":
        pytest.skip("directory reuse validation boundary")
    files = []
    for index in range(32):
        path = pytester.path / f"test_case_{index}.py"
        path.write_text("def test_example():\n    pass\n")
        files.append(str(path))
    result = pytester.runpytest_subprocess("-q", "--boorst", "--boorst-profile", *files)
    result.assert_outcomes(passed=32)
    result.stdout.fnmatch_lines(["*boorst profile*", "*31 directory reports reused*"])


def test_cleanup_unregisters_only_its_profiler():
    import pytest

    manager = pytest.PytestPluginManager()
    cleanup = []
    config = SimpleNamespace(pluginmanager=manager, add_cleanup=cleanup.append)
    _profile.install(config)
    observer = manager.get_plugin("boorst_profile")
    assert isinstance(observer, _profile.Profiler)
    cleanup.pop()()
    assert manager.get_plugin("boorst_profile") is None
    _profile.install(config)
    manager.unregister(manager.get_plugin("boorst_profile"))
    replacement = object()
    manager.register(replacement, "boorst_profile")
    cleanup.pop()()
    assert manager.get_plugin("boorst_profile") is replacement
