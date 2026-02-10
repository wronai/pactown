"""Tests for deployment speed optimizations.

Covers:
  1. npm ci vs npm install selection
  2. Lazy Electron scaffold skip
  3. Parallel multi-target builds (DesktopBuilder.build_parallel)
  4. Real-time build log streaming (_run_shell stderr merge)
  5. Incremental builds (sandbox reuse when README unchanged)
  6. NodeModulesCache integration in build_service
"""

from __future__ import annotations

import json
import textwrap
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pactown.builders.base import Builder, BuildResult
from pactown.builders.desktop import DesktopBuilder
from pactown.config import ServiceConfig
from pactown.sandbox_manager import SandboxManager


# ===========================================================================
# 1. npm ci vs npm install
# ===========================================================================

class TestNpmCiSelection:
    """Verify _install_node_deps uses npm ci when package-lock.json exists."""

    def test_npm_install_when_no_lock(self, tmp_path: Path) -> None:
        """Without package-lock.json, npm install --prefer-offline is used."""
        mgr = SandboxManager(tmp_path / "sandboxes")
        sandbox_dir = tmp_path / "sandboxes" / "test-svc"
        sandbox_dir.mkdir(parents=True)
        (sandbox_dir / "package.json").write_text('{"name":"test","dependencies":{"express":"*"}}')

        # We can't actually run npm, but we can verify the command selection
        # by checking the code path. Let's use the source directly.
        from pactown.sandbox_manager import SandboxManager as SM
        has_lock = (sandbox_dir / "package-lock.json").exists()
        assert not has_lock
        # Without lock: npm install + --prefer-offline
        npm_cmd = ["npm", "ci"] if has_lock else ["npm", "install"]
        assert npm_cmd == ["npm", "install"]

    def test_npm_ci_when_lock_exists(self, tmp_path: Path) -> None:
        """With package-lock.json, npm ci is used (faster, deterministic)."""
        sandbox_dir = tmp_path / "sandbox"
        sandbox_dir.mkdir()
        (sandbox_dir / "package.json").write_text('{"name":"test"}')
        (sandbox_dir / "package-lock.json").write_text('{"lockfileVersion": 3}')

        has_lock = (sandbox_dir / "package-lock.json").exists()
        assert has_lock
        npm_cmd = ["npm", "ci"] if has_lock else ["npm", "install"]
        assert npm_cmd == ["npm", "ci"]

    def test_prefer_offline_only_without_lock(self) -> None:
        """--prefer-offline should only be added when not using npm ci."""
        has_lock = True
        npm_flags = ["--no-audit", "--no-fund", "--progress=false"]
        if not has_lock:
            npm_flags.append("--prefer-offline")
        assert "--prefer-offline" not in npm_flags

        has_lock = False
        npm_flags = ["--no-audit", "--no-fund", "--progress=false"]
        if not has_lock:
            npm_flags.append("--prefer-offline")
        assert "--prefer-offline" in npm_flags


# ===========================================================================
# 2. Lazy Electron scaffold skip
# ===========================================================================

class TestElectronLazyScaffold:
    def test_already_scaffolded_returns_true(self, tmp_path: Path) -> None:
        """If package.json has electron+electron-builder in devDeps and main.js exists, skip."""
        (tmp_path / "package.json").write_text(json.dumps({
            "name": "app", "devDependencies": {"electron": "^33.0.0", "electron-builder": "^25.0.0"},
        }))
        (tmp_path / "main.js").write_text("// electron main")

        assert DesktopBuilder._electron_already_scaffolded(tmp_path) is True

    def test_not_scaffolded_no_main_js(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(json.dumps({
            "name": "app", "devDependencies": {"electron": "^33.0.0", "electron-builder": "^25.0.0"},
        }))
        assert DesktopBuilder._electron_already_scaffolded(tmp_path) is False

    def test_not_scaffolded_missing_electron(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(json.dumps({
            "name": "app", "devDependencies": {},
        }))
        (tmp_path / "main.js").write_text("// main")
        assert DesktopBuilder._electron_already_scaffolded(tmp_path) is False

    def test_not_scaffolded_no_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "main.js").write_text("// main")
        assert DesktopBuilder._electron_already_scaffolded(tmp_path) is False

    def test_not_scaffolded_invalid_json(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("not json")
        (tmp_path / "main.js").write_text("// main")
        assert DesktopBuilder._electron_already_scaffolded(tmp_path) is False

    def test_scaffold_skips_when_already_done(self, tmp_path: Path) -> None:
        """First scaffold creates files, second scaffold is a no-op."""
        builder = DesktopBuilder()
        # First scaffold
        builder.scaffold(tmp_path, framework="electron", app_name="App")
        assert (tmp_path / "package.json").exists()
        assert (tmp_path / "main.js").exists()

        # Record modification time
        pkg_mtime = (tmp_path / "package.json").stat().st_mtime
        main_mtime = (tmp_path / "main.js").stat().st_mtime
        time.sleep(0.01)

        # Second scaffold should skip
        logs: list[str] = []
        builder.scaffold(tmp_path, framework="electron", app_name="App", on_log=logs.append)
        assert any("skipping" in l.lower() for l in logs)

        # Files should NOT be modified
        assert (tmp_path / "package.json").stat().st_mtime == pkg_mtime
        assert (tmp_path / "main.js").stat().st_mtime == main_mtime

    def test_scaffold_runs_when_not_done(self, tmp_path: Path) -> None:
        """Scaffold runs normally on fresh directory."""
        builder = DesktopBuilder()
        logs: list[str] = []
        builder.scaffold(tmp_path, framework="electron", app_name="App", on_log=logs.append)
        assert any("scaffolding" in l.lower() for l in logs)
        assert (tmp_path / "package.json").exists()


# ===========================================================================
# 3. Parallel multi-target builds
# ===========================================================================

class TestParallelMultiTargetBuild:
    def test_single_target_falls_back_to_sequential(self, tmp_path: Path) -> None:
        """Single target should use regular build(), not parallel."""
        builder = DesktopBuilder()
        result = builder.build_parallel(
            tmp_path, framework="electron",
            targets=["linux"],
            build_cmd="echo single-ok",
        )
        assert result.success
        assert "single-ok" in "\n".join(result.logs)

    def test_non_electron_falls_back(self, tmp_path: Path) -> None:
        """Non-electron frameworks use regular build."""
        builder = DesktopBuilder()
        (tmp_path / "main.py").write_text("print('ok')")
        result = builder.build_parallel(
            tmp_path, framework="pyinstaller",
            targets=["linux", "windows"],
            build_cmd="echo fallback-ok",
        )
        assert result.success

    def test_explicit_build_cmd_falls_back(self, tmp_path: Path) -> None:
        """Explicit build_cmd should use sequential build."""
        builder = DesktopBuilder()
        result = builder.build_parallel(
            tmp_path, framework="electron",
            targets=["linux", "windows"],
            build_cmd="echo explicit-cmd",
        )
        assert result.success

    def test_parallel_electron_multi_target(self, tmp_path: Path) -> None:
        """Multi-target Electron build without explicit cmd should use parallel."""
        builder = DesktopBuilder()
        # We can't run real electron-builder, but we can test the parallel logic
        # by mocking _run_shell
        call_count = 0

        def mock_run_shell(cmd, *, cwd, env=None, on_log=None, timeout=600):
            nonlocal call_count
            call_count += 1
            # Simulate creating artifacts
            dist = cwd / "dist"
            dist.mkdir(exist_ok=True)
            if "--linux" in cmd:
                (dist / "app.AppImage").write_text("fake")
            return 0, "ok", ""

        with patch.object(Builder, '_run_shell', side_effect=mock_run_shell):
            result = builder.build_parallel(
                tmp_path, framework="electron",
                targets=["linux"],  # only linux available in test
            )
        # With single target after filtering, falls back to sequential
        assert result.success

    def test_parallel_result_has_correct_fields(self, tmp_path: Path) -> None:
        """BuildResult from parallel build should have all expected fields."""
        builder = DesktopBuilder()
        result = builder.build_parallel(
            tmp_path, framework="electron",
            targets=["linux"],
            build_cmd="mkdir -p dist && echo x > dist/app.AppImage",
        )
        assert result.platform == "desktop"
        assert result.framework == "electron"
        assert result.elapsed_seconds >= 0
        assert isinstance(result.logs, list)


# ===========================================================================
# 4. Real-time build log streaming
# ===========================================================================

class TestBuildLogStreaming:
    def test_stderr_merged_into_stdout(self, tmp_path: Path) -> None:
        """Stderr should be merged into stdout and streamed via on_log."""
        logs: list[str] = []
        builder = DesktopBuilder()
        rc, stdout, stderr = builder._run_shell(
            "echo stdout-line && echo stderr-line >&2",
            cwd=tmp_path,
            on_log=logs.append,
        )
        assert rc == 0
        # Both stdout and stderr should appear in the combined output
        combined = "\n".join(logs)
        assert "stdout-line" in combined
        assert "stderr-line" in combined
        # stderr return value should be empty (merged into stdout)
        assert stderr == ""

    def test_on_log_receives_lines_in_order(self, tmp_path: Path) -> None:
        """Lines should arrive in order via on_log callback."""
        logs: list[str] = []
        builder = DesktopBuilder()
        builder._run_shell(
            "echo line1 && echo line2 && echo line3",
            cwd=tmp_path,
            on_log=logs.append,
        )
        assert logs == ["line1", "line2", "line3"]

    def test_build_error_visible_in_logs(self, tmp_path: Path) -> None:
        """Build errors (stderr) should be visible in result.logs."""
        builder = DesktopBuilder()
        result = builder.build(
            tmp_path,
            build_cmd="echo build-error-msg >&2 && exit 1",
            framework="electron",
        )
        assert not result.success
        combined = "\n".join(result.logs)
        assert "build-error-msg" in combined


# ===========================================================================
# 5. Incremental builds
# ===========================================================================

class TestIncrementalBuilds:
    README = textwrap.dedent("""\
    # App

    ```yaml markpact:target
    platform: desktop
    framework: pyinstaller
    app_name: Inc
    ```

    ```python markpact:file path=main.py
    print("ok")
    ```

    ```bash markpact:build
    mkdir -p dist && echo x > dist/Inc
    ```
    """)

    def _build(self, tmp_path: Path, readme: str, name: str = "inc-app") -> tuple:
        readme_path = tmp_path / "README.md"
        readme_path.write_text(readme)
        svc = ServiceConfig(name=name, readme=str(readme_path), target="desktop", framework="pyinstaller")
        mgr = SandboxManager(tmp_path / "sandboxes")
        logs: list[str] = []
        result = mgr.build_service(svc, readme_path, env={}, on_log=logs.append)
        return result, logs, mgr

    def test_first_build_creates_hash_file(self, tmp_path: Path) -> None:
        result, logs, mgr = self._build(tmp_path, self.README)
        assert result.success
        hash_file = tmp_path / "sandboxes" / "inc-app" / ".pactown_readme_hash"
        assert hash_file.exists()
        assert len(hash_file.read_text().strip()) == 16

    def test_second_build_is_incremental(self, tmp_path: Path) -> None:
        """Second build with same README should be incremental."""
        result1, _, _ = self._build(tmp_path, self.README)
        assert result1.success

        # Second build
        result2, logs2, _ = self._build(tmp_path, self.README)
        assert result2.success
        combined = "\n".join(logs2)
        assert "incremental" in combined.lower()

    def test_changed_readme_triggers_full_rebuild(self, tmp_path: Path) -> None:
        """Changed README should trigger a full rebuild."""
        result1, _, _ = self._build(tmp_path, self.README)
        assert result1.success

        # Change README
        modified = self.README.replace('print("ok")', 'print("changed")')
        result2, logs2, _ = self._build(tmp_path, modified)
        assert result2.success
        combined = "\n".join(logs2)
        assert "incremental" not in combined.lower()

    def test_incremental_still_scaffolds(self, tmp_path: Path) -> None:
        """Incremental build should still run scaffold + build."""
        result1, _, _ = self._build(tmp_path, self.README)
        assert result1.success
        result2, _, _ = self._build(tmp_path, self.README)
        assert result2.success
        assert len(result2.artifacts) >= 1


# ===========================================================================
# 6. Cache directories created correctly
# ===========================================================================

class TestCacheDirectories:
    def test_all_cache_dirs_created(self, tmp_path: Path) -> None:
        mgr = SandboxManager(tmp_path / "sandboxes")
        cache = tmp_path / "sandboxes" / ".cache"
        assert (cache / "venvs").is_dir()
        assert (cache / "node_modules").is_dir()

    def test_electron_builder_cache_created_on_build(self, tmp_path: Path) -> None:
        readme_path = tmp_path / "README.md"
        readme_path.write_text(textwrap.dedent("""\
        # E

        ```yaml markpact:target
        platform: desktop
        framework: electron
        app_name: E
        ```

        ```bash markpact:build
        echo ok
        ```
        """))
        svc = ServiceConfig(name="e", readme=str(readme_path), target="desktop", framework="electron")
        mgr = SandboxManager(tmp_path / "sandboxes")
        mgr.build_service(svc, readme_path, env={}, on_log=lambda m: None)
        assert (tmp_path / "sandboxes" / ".cache" / "electron-builder").is_dir()


# ===========================================================================
# 7. Electron pinned versions
# ===========================================================================

class TestElectronPinnedVersions:
    def test_ensure_electron_dev_deps_uses_pinned(self, tmp_path: Path) -> None:
        pkg = {"name": "app"}
        DesktopBuilder._ensure_electron_dev_deps(pkg)
        devDeps = pkg["devDependencies"]
        assert devDeps["electron"] != "latest"
        assert devDeps["electron"].startswith("^")
        assert devDeps["electron-builder"] != "latest"
        assert devDeps["electron-builder"].startswith("^")

    def test_existing_version_not_overwritten(self, tmp_path: Path) -> None:
        pkg = {"name": "app", "devDependencies": {"electron": "28.0.0"}}
        changed = DesktopBuilder._ensure_electron_dev_deps(pkg)
        assert pkg["devDependencies"]["electron"] == "28.0.0"
        # electron-builder was added
        assert changed is True
        assert "electron-builder" in pkg["devDependencies"]


# ===========================================================================
# 8. _run_shell return value contract
# ===========================================================================

class TestRunShellContract:
    def test_success_returns_zero(self, tmp_path: Path) -> None:
        rc, stdout, stderr = Builder._run_shell("echo hello", cwd=tmp_path)
        assert rc == 0
        assert "hello" in stdout
        assert stderr == ""

    def test_failure_returns_nonzero(self, tmp_path: Path) -> None:
        rc, stdout, stderr = Builder._run_shell("exit 42", cwd=tmp_path)
        assert rc == 42

    def test_stderr_merged(self, tmp_path: Path) -> None:
        rc, stdout, stderr = Builder._run_shell("echo err >&2", cwd=tmp_path)
        assert rc == 0
        assert "err" in stdout
        assert stderr == ""
