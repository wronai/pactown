"""Parallel execution utilities for pactown."""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Optional

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

console = Console()


@dataclass
class TaskResult:
    """Result of a parallel task."""
    name: str
    success: bool
    duration: float
    result: Any = None
    error: Optional[str] = None


def run_parallel(
    tasks: dict[str, Callable[[], Any]],
    max_workers: int = 4,
    show_progress: bool = True,
    description: str = "Running tasks",
) -> dict[str, TaskResult]:
    """
    Run multiple tasks in parallel using ThreadPoolExecutor.

    Args:
        tasks: Dict of {name: callable} to run
        max_workers: Maximum parallel workers
        show_progress: Show progress bar
        description: Progress description

    Returns:
        Dict of {name: TaskResult}
    """
    results: dict[str, TaskResult] = {}

    if not tasks:
        return results

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        start_times = {}

        for name, func in tasks.items():
            start_times[name] = time.time()
            futures[executor.submit(func)] = name

        if show_progress:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(description, total=len(tasks))

                for future in as_completed(futures):
                    name = futures[future]
                    duration = time.time() - start_times[name]

                    try:
                        result = future.result()
                        results[name] = TaskResult(
                            name=name,
                            success=True,
                            duration=duration,
                            result=result,
                        )
                    except Exception as e:
                        results[name] = TaskResult(
                            name=name,
                            success=False,
                            duration=duration,
                            error=str(e),
                        )

                    progress.advance(task)
        else:
            for future in as_completed(futures):
                name = futures[future]
                duration = time.time() - start_times[name]

                try:
                    result = future.result()
                    results[name] = TaskResult(
                        name=name,
                        success=True,
                        duration=duration,
                        result=result,
                    )
                except Exception as e:
                    results[name] = TaskResult(
                        name=name,
                        success=False,
                        duration=duration,
                        error=str(e),
                    )

    return results


def run_in_dependency_waves(
    tasks: dict[str, Callable[[], Any]],
    dependencies: dict[str, list[str]],
    max_workers: int = 4,
    on_complete: Optional[Callable[[str, TaskResult], None]] = None,
) -> dict[str, TaskResult]:
    """
    Run tasks in waves based on dependencies.

    Services with no unmet dependencies run in parallel.
    When a wave completes, next wave starts.

    Args:
        tasks: Dict of {name: callable}
        dependencies: Dict of {name: [dependency_names]}
        max_workers: Max parallel workers per wave
        on_complete: Callback when task completes

    Returns:
        Dict of {name: TaskResult}
    """
    results: dict[str, TaskResult] = {}
    completed = set()
    remaining = set(tasks.keys())

    while remaining:
        # Find tasks with all dependencies satisfied
        ready = []
        for name in remaining:
            deps = dependencies.get(name, [])
            if all(d in completed for d in deps):
                ready.append(name)

        if not ready:
            # Circular dependency or missing dependency
            raise ValueError(f"Cannot resolve dependencies for: {remaining}")

        # Run ready tasks in parallel
        wave_tasks = {name: tasks[name] for name in ready}
        wave_results = run_parallel(wave_tasks, max_workers=max_workers, show_progress=False)

        for name, result in wave_results.items():
            results[name] = result
            remaining.remove(name)

            if result.success:
                completed.add(name)

            if on_complete:
                on_complete(name, result)

        # If any task in wave failed, stop
        if any(not r.success for r in wave_results.values()):
            break

    return results


async def run_parallel_async(
    tasks: dict[str, Callable[[], Any]],
    max_concurrent: int = 4,
) -> dict[str, TaskResult]:
    """
    Run tasks using asyncio with a semaphore for concurrency control.

    Uses run_in_executor for CPU-bound tasks.
    """
    results: dict[str, TaskResult] = {}
    semaphore = asyncio.Semaphore(max_concurrent)

    async def run_task(name: str, func: Callable) -> TaskResult:
        async with semaphore:
            start = time.time()
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, func)
                return TaskResult(
                    name=name,
                    success=True,
                    duration=time.time() - start,
                    result=result,
                )
            except Exception as e:
                return TaskResult(
                    name=name,
                    success=False,
                    duration=time.time() - start,
                    error=str(e),
                )

    coros = [run_task(name, func) for name, func in tasks.items()]
    task_results = await asyncio.gather(*coros)

    for result in task_results:
        results[result.name] = result

    return results


class ParallelSandboxBuilder:
    """Build multiple sandboxes in parallel."""

    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self._lock = Lock()

    def build_sandboxes(
        self,
        services: list[tuple[str, Path, Callable]],
        on_complete: Optional[Callable[[str, bool, float], None]] = None,
    ) -> dict[str, TaskResult]:
        """
        Build sandboxes for multiple services in parallel.

        Args:
            services: List of (name, readme_path, build_func)
            on_complete: Callback(name, success, duration)

        Returns:
            Dict of results
        """
        tasks = {}
        for name, readme_path, build_func in services:
            tasks[name] = build_func

        def callback(name: str, result: TaskResult):
            if on_complete:
                on_complete(name, result.success, result.duration)

        return run_parallel(
            tasks,
            max_workers=self.max_workers,
            show_progress=True,
            description="Building sandboxes",
        )


def format_parallel_results(results: dict[str, TaskResult]) -> str:
    """Format parallel execution results for display."""
    lines = []
    total_time = sum(r.duration for r in results.values())

    successful = [r for r in results.values() if r.success]
    failed = [r for r in results.values() if not r.success]

    lines.append(f"Completed: {len(successful)}/{len(results)} tasks")
    lines.append(f"Total time: {total_time:.2f}s")

    if failed:
        lines.append("\nFailed:")
        for r in failed:
            lines.append(f"  ✗ {r.name}: {r.error}")

    return "\n".join(lines)
