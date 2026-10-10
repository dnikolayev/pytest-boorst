import json
from types import SimpleNamespace

import pytest
from pytest_boorst import _static


@pytest.fixture
def run_static(pytester, monkeypatch):
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.delenv("PYTEST_BOORST", raising=False)
    pytester.makeini("[pytest]")

    def run(*args):
        return pytester.runpytest_subprocess("-p", "pytest_boorst.plugin", "-q", *args)

    return run


OBSERVER = """
import json
from pathlib import Path
import pytest
nodes, phases = [], []
@pytest.fixture
def answer():
    yield 42

def pytest_collection_finish(session):
    nodes.extend(item.nodeid for item in session.items)

def pytest_runtest_logreport(report):
    phases.append([report.nodeid, report.when, report.outcome])

def pytest_sessionfinish(session, exitstatus):
    Path('receipt.json').write_text(json.dumps([nodes, phases, int(exitstatus)]))
"""


def test_retained_tests_have_stock_ids_fixtures_and_outcomes(pytester, run_static):
    pytester.makeconftest(OBSERVER)
    pytester.makepyfile(
        test_real="""
        import pytest
        @pytest.mark.parametrize('value', [1, 2])
        def test_param(answer, value):
            assert answer == 42 and value > 0
        class TestInheritedBase:
            def test_base(self, answer):
                assert answer == 42
        class TestInherited(TestInheritedBase):
            pass
        def test_failure(answer):
            assert answer == 0
        @pytest.mark.skip(reason='example')
        def test_skip():
            pass
        """,
        test_empty="import math\nVALUE = math.pi\n",
    )
    baseline = run_static()
    stock = json.loads((pytester.path / "receipt.json").read_text())
    result = run_static("--boorst", "--boorst-static-discovery")
    assert json.loads((pytester.path / "receipt.json").read_text()) == stock
    assert result.ret == baseline.ret == pytest.ExitCode.TESTS_FAILED
    result.stdout.fnmatch_lines(
        [
            "*runtime-generated, imported or plugin-defined tests may be omitted*",
            "*1 files skipped, 1 candidate files retained*incomplete collection is possible*",
        ]
    )


def test_skipped_module_code_never_runs_and_default_is_unchanged(pytester, run_static):
    pytester.makepyfile(
        test_empty="raise RuntimeError('empty-module-imported')",
        test_real="def test_real():\n    assert True",
    )
    static = run_static("--boorst-static-discovery")
    static.assert_outcomes(passed=1)
    baseline = run_static()
    assert baseline.ret == pytest.ExitCode.INTERRUPTED
    baseline.stdout.fnmatch_lines(["*RuntimeError: empty-module-imported*"])


def test_source_errors_and_explicit_files_stay_with_pytest(pytester, run_static):
    pytester.makepyfile(test_broken="this is invalid syntax !")
    result = run_static("--boorst-static-discovery")
    assert result.ret == pytest.ExitCode.INTERRUPTED
    result.stdout.fnmatch_lines(
        ["*SyntaxError*", "*1 files retained after source errors*"]
    )
    (pytester.path / "test_broken.py").unlink()
    pytester.makepyfile(test_empty="print('explicit module imported')")
    result = run_static("--boorst-static-discovery", "test_empty.py", "-s")
    assert result.ret == pytest.ExitCode.NO_TESTS_COLLECTED
    result.stdout.fnmatch_lines(["*explicit module imported*", "*0 examined*"])
    missing = run_static("--boorst-static-discovery", "missing.py")
    assert missing.ret == pytest.ExitCode.USAGE_ERROR


def test_patterns_testpaths_ignores_and_selectors_use_normal_pytest(
    pytester, run_static
):
    pytester.makeini("""
        [pytest]
        testpaths = suite
        python_files = case_*.py
        python_functions = check_
        python_classes = Spec
        norecursedirs = excluded
    """)
    suite = pytester.path / "suite"
    suite.mkdir()
    (suite / "case_real.py").write_text(
        "class SpecAnswer:\n    def check_answer(self):\n        assert True\n"
    )
    (suite / "case_empty.py").write_text("raise RuntimeError('prefilter')")
    for name in ("case_ignored.py", "case_glob.py", "test_other.py"):
        (suite / name).write_text("raise RuntimeError('ignored')")
    excluded = suite / "excluded"
    excluded.mkdir()
    (excluded / "case_error.py").write_text("raise RuntimeError('norecursedirs')")
    result = run_static(
        "--boorst-static-discovery",
        "--ignore=suite/case_ignored.py",
        "--ignore-glob=*case_glob.py",
    )
    result.assert_outcomes(passed=1)
    selected = run_static(
        "--boorst-static-discovery",
        "suite/case_real.py::SpecAnswer::check_answer",
        "-k",
        "answer",
    )
    selected.assert_outcomes(passed=1)
    selected.stdout.fnmatch_lines(["*0 candidate files retained*"])


def test_runtime_defined_tests_can_be_omitted_with_an_explicit_notice(
    pytester, run_static
):
    pytester.makepyfile(test_dynamic="exec('def test_dynamic(): pass')")
    baseline = run_static()
    baseline.assert_outcomes(passed=1)
    static = run_static("--boorst-static-discovery")
    assert static.ret == pytest.ExitCode.NO_TESTS_COLLECTED
    static.stdout.fnmatch_lines(["*1 files skipped*incomplete collection is possible*"])


def test_conditional_definitions_are_retained(pytester, run_static):
    pytester.makepyfile(test_conditional="if True:\n    def test_real():\n        pass")
    run_static("--boorst-static-discovery").assert_outcomes(passed=1)


def test_read_errors_fall_back_without_being_hidden(tmp_path, monkeypatch):
    path = tmp_path / "test_unreadable.py"
    path.write_text("VALUE = 1")
    config = SimpleNamespace(
        getini=lambda name: ["test_*.py"],
        getoption=lambda name, default=None: default,
    )
    prefilter = _static.StaticDiscovery(config)

    def unreadable(path):
        raise PermissionError("synthetic read failure")

    monkeypatch.setattr(_static.tokenize, "open", unreadable)
    assert prefilter.pytest_ignore_collect(path, config) is None
    assert prefilter.counts == dict(examined=1, candidates=0, skipped=0, fallback=1)


@pytest.mark.parametrize(
    "options", [{"numprocesses": 1}, {"dist": "load"}, {"tx": ["popen"]}]
)
def test_parallel_options_are_rejected(options):
    config = SimpleNamespace(
        getoption=lambda name, default=None: options.get(name, default)
    )
    with pytest.raises(pytest.UsageError, match="requires serial pytest"):
        _static.install(config)


def test_existing_ignore_hook_can_keep_a_file(pytester, run_static):
    pytester.makeconftest("""
        def pytest_ignore_collect(collection_path, config):
            if collection_path.name == "test_dynamic.py":
                return False
    """)
    pytester.makepyfile(test_dynamic="exec('def test_dynamic(): pass')")
    result = run_static("--boorst-static-discovery")
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["*0 examined*"])


def test_module_doctests_keep_stock_ids_and_failure(pytester, run_static):
    pytester.makeconftest(OBSERVER)
    pytester.makepyfile(test_doc='"""\n>>> 1 + 1\n3\n"""')
    baseline = run_static("--doctest-modules")
    stock = json.loads((pytester.path / "receipt.json").read_text())
    static = run_static("--doctest-modules", "--boorst-static-discovery")
    assert json.loads((pytester.path / "receipt.json").read_text()) == stock
    assert static.ret == baseline.ret == pytest.ExitCode.TESTS_FAILED
    static.assert_outcomes(failed=1)
    static.stdout.fnmatch_lines(["*0 files skipped*0 examined*"])


def _benchmark_module():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "boorst_static_benchmark",
        Path(__file__).resolve().parents[1] / "benchmarks/static_discovery.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_benchmark_hashes_the_imported_modules(tmp_path, monkeypatch):
    import hashlib

    namespace = {}
    exec(_benchmark_module().OBSERVER, namespace)
    expected = {}
    for name in ("_static", "plugin"):
        installed = tmp_path / f"{name}.py"
        installed.write_text(f"# synthetic installed {name}\n")
        monkeypatch.setattr(namespace[name], "__file__", str(installed))
        expected[f"{name}.py"] = hashlib.sha256(installed.read_bytes()).hexdigest()
    monkeypatch.chdir(tmp_path)
    session = SimpleNamespace(
        config=SimpleNamespace(
            pluginmanager=SimpleNamespace(get_plugin=lambda name: None)
        )
    )
    namespace["pytest_sessionfinish"](session, 0)
    assert (
        json.loads((tmp_path / "receipt.json").read_text())["source_sha256"] == expected
    )


@pytest.mark.parametrize("changed", [False, True])
def test_benchmark_uses_selected_interpreter_hashes_consistently(
    tmp_path, monkeypatch, changed
):
    module = _benchmark_module()
    expected = {"_static.py": "a" * 64, "plugin.py": "b" * 64}
    calls = []

    def run(command, *, cwd, **kwargs):
        assert command[0] == "selected-interpreter"
        assert kwargs["timeout"] == 180
        calls.append(command)
        hashes = dict(expected)
        if changed and len(calls) == 2:
            hashes["_static.py"] = "c" * 64
        (cwd / "receipt.json").write_text(
            json.dumps(
                dict(
                    nodes=["test_example.py::test_example"],
                    phases=[],
                    exitstatus=0,
                    counts={},
                    python="example",
                    pytest="9.1.1",
                    source_sha256=hashes,
                )
            )
        )
        return SimpleNamespace(returncode=0)

    output = tmp_path / "result.json"
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(
        module.os.sys,
        "argv",
        ["benchmark", "--python", "selected-interpreter", "--output", str(output)],
    )
    if changed:
        with pytest.raises(RuntimeError, match="loaded source changed"):
            module.main()
        assert not output.exists()
    else:
        module.main()
        assert json.loads(output.read_text())["source_sha256"] == expected
        assert len(calls) == 12
