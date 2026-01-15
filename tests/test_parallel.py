"""Tests for parallel execution utilities."""

import time

from pactown.parallel import (
    TaskResult,
    run_in_dependency_waves,
    run_parallel,
)


def test_run_parallel_basic():
    """Test basic parallel execution."""
    results = {}

    def task_a():
        time.sleep(0.1)
        return "a"

    def task_b():
        time.sleep(0.1)
        return "b"

    tasks = {"a": task_a, "b": task_b}
    results = run_parallel(tasks, max_workers=2, show_progress=False)

    assert len(results) == 2
    assert results["a"].success
    assert results["a"].result == "a"
    assert results["b"].success
    assert results["b"].result == "b"


def test_run_parallel_with_error():
    """Test parallel execution with failing task."""
    def task_ok():
        return "ok"

    def task_fail():
        raise ValueError("test error")

    tasks = {"ok": task_ok, "fail": task_fail}
    results = run_parallel(tasks, max_workers=2, show_progress=False)

    assert results["ok"].success
    assert not results["fail"].success
    assert "test error" in results["fail"].error


def test_run_parallel_timing():
    """Test that parallel execution is faster than sequential."""
    def slow_task():
        time.sleep(0.1)
        return True

    tasks = {f"task_{i}": slow_task for i in range(4)}

    start = time.time()
    results = run_parallel(tasks, max_workers=4, show_progress=False)
    elapsed = time.time() - start

    # Should complete in ~0.1s (parallel), not ~0.4s (sequential)
    assert elapsed < 0.3
    assert all(r.success for r in results.values())


def test_run_in_dependency_waves():
    """Test wave-based execution with dependencies."""
    execution_order = []

    def make_task(name):
        def task():
            execution_order.append(name)
            time.sleep(0.05)
            return name
        return task

    tasks = {
        "a": make_task("a"),
        "b": make_task("b"),
        "c": make_task("c"),
    }

    # c depends on a and b
    dependencies = {
        "a": [],
        "b": [],
        "c": ["a", "b"],
    }

    results = run_in_dependency_waves(tasks, dependencies, max_workers=2)

    assert len(results) == 3
    assert all(r.success for r in results.values())

    # c should be after a and b
    assert execution_order.index("c") > execution_order.index("a")
    assert execution_order.index("c") > execution_order.index("b")


def test_run_in_dependency_waves_diamond():
    """Test diamond dependency pattern."""
    execution_order = []

    def make_task(name):
        def task():
            execution_order.append(name)
            return name
        return task

    # Diamond: d depends on b,c; b,c depend on a
    tasks = {
        "a": make_task("a"),
        "b": make_task("b"),
        "c": make_task("c"),
        "d": make_task("d"),
    }

    dependencies = {
        "a": [],
        "b": ["a"],
        "c": ["a"],
        "d": ["b", "c"],
    }

    results = run_in_dependency_waves(tasks, dependencies, max_workers=2)

    assert all(r.success for r in results.values())

    # a must be first
    assert execution_order.index("a") == 0
    # d must be last
    assert execution_order.index("d") == 3


def test_task_result_dataclass():
    """Test TaskResult dataclass."""
    result = TaskResult(
        name="test",
        success=True,
        duration=1.5,
        result="value",
    )

    assert result.name == "test"
    assert result.success
    assert result.duration == 1.5
    assert result.result == "value"
    assert result.error is None
