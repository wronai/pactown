"""Builder for desktop applications (Electron, Tauri, PyInstaller, Tkinter, PyQt)."""

from __future__ import annotations

import json
import platform
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Optional

from .base import Builder, BuildError, BuildResult


class DesktopBuilder(Builder):
    """Builds desktop application artifacts from a markpact sandbox."""

    @property
    def platform_name(self) -> str:
        return "desktop"

    # ------------------------------------------------------------------
    # Scaffold
    # ------------------------------------------------------------------

    def scaffold(
        self,
        sandbox_path: Path,
        *,
        framework: str,
        app_name: str = "app",
        extra: Optional[dict[str, Any]] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> None:
        fw = (framework or "").strip().lower()
        if fw == "electron":
            self._scaffold_electron(sandbox_path, app_name=app_name, extra=extra, on_log=on_log)
        elif fw == "tauri":
            self._scaffold_tauri(sandbox_path, app_name=app_name, extra=extra, on_log=on_log)
        elif fw in ("pyinstaller", "tkinter", "pyqt"):
            self._scaffold_python_desktop(sandbox_path, framework=fw, app_name=app_name, extra=extra, on_log=on_log)
        else:
            self._log(on_log, f"[desktop] No scaffolding for framework '{fw}' – using files as-is")

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(
        self,
        sandbox_path: Path,
        *,
        build_cmd: Optional[str] = None,
        framework: str = "",
        targets: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> BuildResult:
        fw = (framework or "").strip().lower()
        t0 = time.monotonic()
        logs: list[str] = []

        def _log(msg: str) -> None:
            logs.append(msg)
            self._log(on_log, msg)

        # Resolve build command
        cmd = build_cmd
        if not cmd:
            cmd = self._default_build_cmd(fw, targets)

        # Always filter electron-builder commands (explicit or generated)
        if cmd and "electron-builder" in cmd:
            cmd = self._filter_electron_builder_cmd(cmd)

        if not cmd:
            return BuildResult(
                success=False,
                platform="desktop",
                framework=fw,
                message="No build command specified and no default known for this framework",
                logs=logs,
            )

        # Patch Electron main.js for AppImage sandbox compatibility
        if fw == "electron":
            self._patch_electron_no_sandbox(sandbox_path, on_log)

        _log(f"[desktop] Building with framework={fw} targets={targets or []}")
        _log(f"[desktop] $ {cmd}")

        rc, stdout, stderr = self._run_shell(cmd, cwd=sandbox_path, env=env, on_log=on_log)

        elapsed = time.monotonic() - t0

        if rc != 0:
            _log(f"[desktop] Build failed (exit {rc})")
            if stderr:
                _log(f"[desktop] STDERR: {stderr[:2000]}")
            return BuildResult(
                success=False,
                platform="desktop",
                framework=fw,
                message=f"Build failed with exit code {rc}",
                logs=logs,
                build_cmd=cmd,
                elapsed_seconds=elapsed,
            )

        artifacts = self._collect_artifacts(sandbox_path, fw)
        _log(f"[desktop] Build OK – {len(artifacts)} artifact(s) in {elapsed:.1f}s")

        return BuildResult(
            success=True,
            platform="desktop",
            framework=fw,
            artifacts=artifacts,
            output_dir=sandbox_path / "dist",
            message=f"Desktop build succeeded ({len(artifacts)} artifacts)",
            logs=logs,
            build_cmd=cmd,
            elapsed_seconds=elapsed,
        )

    # ------------------------------------------------------------------
    # Scaffolding helpers
    # ------------------------------------------------------------------

    # Packages that electron-builder requires in devDependencies, not dependencies.
    _ELECTRON_DEV_ONLY = {"electron", "electron-builder", "electron-packager"}

    @staticmethod
    def _electron_already_scaffolded(sandbox_path: Path) -> bool:
        """Quick check whether Electron scaffold was already applied."""
        pkg_json = sandbox_path / "package.json"
        main_js = sandbox_path / "main.js"
        if not pkg_json.exists() or not main_js.exists():
            return False
        try:
            pkg = json.loads(pkg_json.read_text())
        except Exception:
            return False
        dev = pkg.get("devDependencies", {})
        return "electron" in dev and "electron-builder" in dev

    @classmethod
    def _patch_electron_no_sandbox(
        cls, sandbox_path: Path, on_log: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """Inject ``app.commandLine.appendSwitch('no-sandbox')`` into main.js.

        AppImage on Linux extracts to /tmp so the SUID chrome-sandbox
        binary cannot have proper ownership/permissions.  Without
        ``--no-sandbox`` the app crashes immediately.

        Returns True if the file was patched.
        """
        main_js = sandbox_path / "main.js"
        if not main_js.exists():
            return False
        src = main_js.read_text()
        if "no-sandbox" in src:
            return False  # already patched

        patch_line = "\n// AppImage on Linux requires --no-sandbox\napp.commandLine.appendSwitch('no-sandbox');\n"
        idx: int | None = None

        # 1. CommonJS: require('electron') / require("electron")
        for needle in ("require('electron')", 'require("electron")'):
            if needle in src:
                idx = src.index(needle) + len(needle)
                break

        # 2. ES module: import ... from 'electron' / from "electron"
        if idx is None:
            for needle in ("from 'electron'", 'from "electron"'):
                if needle in src:
                    idx = src.index(needle) + len(needle)
                    break

        # 3. Fallback: prepend before app.whenReady or app.on
        if idx is None:
            for marker in ("app.whenReady", "app.on("):
                if marker in src:
                    idx = src.index(marker)
                    patch_line = "// AppImage on Linux requires --no-sandbox\napp.commandLine.appendSwitch('no-sandbox');\n\n"
                    break

        # 4. Ultimate fallback: prepend at top of file
        if idx is None:
            patch_line = "// AppImage on Linux requires --no-sandbox\nconst { app: _appSandboxFix } = require('electron');\n_appSandboxFix.commandLine.appendSwitch('no-sandbox');\n\n"
            patched = patch_line + src
            main_js.write_text(patched)
            if on_log:
                cls._log(on_log, "[desktop] Patched main.js with --no-sandbox (prepended)")
            return True

        # Find end of the matched line (after semicolon/newline)
        rest = src[idx:]
        newline_pos = rest.find("\n")
        if newline_pos >= 0:
            idx += newline_pos + 1
        else:
            idx = len(src)

        patched = src[:idx] + patch_line + src[idx:]
        main_js.write_text(patched)
        if on_log:
            cls._log(on_log, "[desktop] Patched main.js with --no-sandbox for AppImage")
        return True

    def _scaffold_electron(
        self,
        sandbox_path: Path,
        *,
        app_name: str,
        extra: Optional[dict[str, Any]],
        on_log: Optional[Callable[[str], None]],
    ) -> None:
        if self._electron_already_scaffolded(sandbox_path):
            self._log(on_log, "[desktop] Electron scaffold already applied – skipping")
            return
        self._log(on_log, "[desktop] Scaffolding Electron app")
        pkg_json = sandbox_path / "package.json"
        if pkg_json.exists():
            # Merge Electron-specific fields into existing package.json
            try:
                pkg = json.loads(pkg_json.read_text())
            except Exception:
                pkg = {}
            changed = False
            if "main" not in pkg:
                pkg["main"] = "main.js"
                changed = True
            if not pkg.get("description"):
                pkg["description"] = f"{app_name} – built with Pactown"
                changed = True
            if not pkg.get("author"):
                pkg["author"] = "pactown"
                changed = True
            if "scripts" not in pkg:
                pkg["scripts"] = {
                    "start": "electron .",
                    "build": "electron-builder --linux",
                }
                changed = True
            if "build" not in pkg:
                pkg["build"] = {
                    "appId": (extra or {}).get("app_id", f"com.pactown.{app_name}"),
                    "productName": app_name,
                    "linux": {"target": ["AppImage"]},
                    "win": {"target": ["nsis"]},
                    "mac": {"target": ["dmg"]},
                }
                changed = True
            # electron-builder requires electron/electron-builder in devDependencies
            changed = self._move_to_dev_deps(pkg) or changed
            changed = self._ensure_electron_dev_deps(pkg) or changed
            if changed:
                pkg_json.write_text(json.dumps(pkg, indent=2))
        else:
            width = (extra or {}).get("window_width", 1024)
            height = (extra or {}).get("window_height", 768)
            pkg = {
                "name": app_name,
                "version": "1.0.0",
                "description": f"{app_name} – built with Pactown",
                "author": "pactown",
                "main": "main.js",
                "scripts": {
                    "start": "electron .",
                    "build": "electron-builder --linux",
                },
                "devDependencies": {},
                "build": {
                    "appId": (extra or {}).get("app_id", f"com.pactown.{app_name}"),
                    "productName": app_name,
                    "linux": {"target": ["AppImage"]},
                    "win": {"target": ["nsis"]},
                    "mac": {"target": ["dmg"]},
                },
            }
            self._move_to_dev_deps(pkg)
            self._ensure_electron_dev_deps(pkg)
            pkg_json.write_text(json.dumps(pkg, indent=2))

        main_js = sandbox_path / "main.js"
        if not main_js.exists():
            width = (extra or {}).get("window_width", 1024)
            height = (extra or {}).get("window_height", 768)
            main_js.write_text(
                f"""\
const {{ app, BrowserWindow }} = require('electron');
const path = require('path');

// AppImage on Linux requires --no-sandbox
app.commandLine.appendSwitch('no-sandbox');

function createWindow() {{
    const win = new BrowserWindow({{
        width: {width},
        height: {height},
        webPreferences: {{ preload: path.join(__dirname, 'preload.js') }},
    }});
    win.loadFile('index.html');
}}

app.whenReady().then(createWindow);
app.on('window-all-closed', () => {{ if (process.platform !== 'darwin') app.quit(); }});
"""
            )

    @classmethod
    def _move_to_dev_deps(cls, pkg: dict) -> bool:
        """Move electron/electron-builder from dependencies to devDependencies.

        Returns True if anything was moved.
        """
        deps = pkg.get("dependencies")
        if not isinstance(deps, dict):
            return False
        dev_deps = pkg.setdefault("devDependencies", {})
        moved = False
        for name in list(deps):
            if name in cls._ELECTRON_DEV_ONLY:
                dev_deps[name] = deps.pop(name)
                moved = True
        return moved

    @staticmethod
    def _ensure_electron_dev_deps(pkg: dict) -> bool:
        """Ensure electron and electron-builder are in devDependencies.

        Returns True if any entry was added.
        """
        _PINNED = {"electron": "^33.0.0", "electron-builder": "^25.0.0"}
        dev_deps = pkg.setdefault("devDependencies", {})
        added = False
        for name, version in _PINNED.items():
            if name not in dev_deps:
                dev_deps[name] = version
                added = True
        return added

    def _scaffold_tauri(
        self,
        sandbox_path: Path,
        *,
        app_name: str,
        extra: Optional[dict[str, Any]],
        on_log: Optional[Callable[[str], None]],
    ) -> None:
        self._log(on_log, "[desktop] Scaffolding Tauri app")
        tauri_dir = sandbox_path / "src-tauri"
        tauri_dir.mkdir(parents=True, exist_ok=True)
        conf = tauri_dir / "tauri.conf.json"
        if not conf.exists():
            width = (extra or {}).get("window_width", 1024)
            height = (extra or {}).get("window_height", 768)
            config = {
                "build": {"distDir": "../dist", "devPath": "http://localhost:1420"},
                "package": {"productName": app_name, "version": "1.0.0"},
                "tauri": {
                    "bundle": {
                        "active": True,
                        "identifier": (extra or {}).get("app_id", f"com.pactown.{app_name}"),
                        "targets": "all",
                    },
                    "windows": [{"title": app_name, "width": width, "height": height}],
                },
            }
            conf.write_text(json.dumps(config, indent=2))

    def _scaffold_python_desktop(
        self,
        sandbox_path: Path,
        *,
        framework: str,
        app_name: str,
        extra: Optional[dict[str, Any]],
        on_log: Optional[Callable[[str], None]],
    ) -> None:
        self._log(on_log, f"[desktop] Scaffolding Python desktop ({framework})")
        spec = sandbox_path / f"{app_name}.spec"
        if not spec.exists() and framework in ("pyinstaller", "tkinter", "pyqt"):
            icon = (extra or {}).get("icon", "")
            icon_line = f"icon='{icon}'," if icon else ""
            spec.write_text(
                f"""\
# -*- mode: python ; coding: utf-8 -*-
a = Analysis(['main.py'], pathex=[], binaries=[], datas=[], hiddenimports=[], hookspath=[])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='{app_name}', debug=False, strip=False, upx=True, console=False, {icon_line})
"""
            )

    # ------------------------------------------------------------------
    # Defaults & artifact collection
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_electron_builder_cmd(cmd: str) -> str:
        """Strip unsupported platform flags from an explicit electron-builder command."""
        host = platform.system().lower()
        has_wine = shutil.which("wine") is not None or shutil.which("wine64") is not None
        parts = cmd.split()
        filtered: list[str] = []
        for p in parts:
            if p == "--windows" and host != "windows" and not has_wine:
                continue
            if p == "--mac" and host != "darwin":
                continue
            filtered.append(p)
        # Ensure at least one platform flag remains
        has_platform = any(f in filtered for f in ("--linux", "--windows", "--mac"))
        if not has_platform:
            filtered.append("--linux")
        return " ".join(filtered)

    @staticmethod
    def _electron_builder_flags(targets: Optional[list[str]]) -> list[str]:
        """Map target names to electron-builder CLI flags, skipping unsupported cross-compilation."""
        _FLAG_MAP = {
            "linux": "--linux",
            "windows": "--windows",
            "win": "--windows",
            "macos": "--mac",
            "mac": "--mac",
            "darwin": "--mac",
        }
        host = platform.system().lower()  # 'linux', 'darwin', 'windows'
        has_wine = shutil.which("wine") is not None or shutil.which("wine64") is not None

        flags: list[str] = []
        for t in (targets or ["linux"]):
            flag = _FLAG_MAP.get(t.lower())
            if not flag:
                continue
            # Cross-compilation checks
            if flag == "--windows" and host != "windows" and not has_wine:
                continue
            if flag == "--mac" and host != "darwin":
                continue
            if flag not in flags:
                flags.append(flag)
        return flags or ["--linux"]

    @classmethod
    def _default_build_cmd(cls, framework: str, targets: Optional[list[str]]) -> str:
        fw = (framework or "").strip().lower()
        if fw == "electron":
            flags = cls._electron_builder_flags(targets)
            return "npx electron-builder " + " ".join(flags)
        if fw == "tauri":
            return "npx tauri build"
        if fw in ("pyinstaller", "tkinter", "pyqt"):
            return "pyinstaller --onefile --windowed main.py"
        if fw == "flutter":
            t = (targets or ["linux"])[0]
            return f"flutter build {t}"
        return ""

    def build_parallel(
        self,
        sandbox_path: Path,
        *,
        build_cmd: Optional[str] = None,
        framework: str = "",
        targets: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
        on_log: Optional[Callable[[str], None]] = None,
        max_workers: int = 3,
    ) -> BuildResult:
        """Build for multiple targets in parallel (Electron only).

        Each target (linux, windows, mac) is built in a separate thread.
        Falls back to sequential build for non-Electron frameworks or
        single-target builds.
        """
        fw = (framework or "").strip().lower()
        effective_targets = targets or ["linux"]

        # Only parallelize Electron multi-target builds
        if fw != "electron" or len(effective_targets) <= 1 or build_cmd:
            return self.build(
                sandbox_path, build_cmd=build_cmd, framework=framework,
                targets=targets, env=env, on_log=on_log,
            )

        t0 = time.monotonic()
        logs: list[str] = []
        all_artifacts: list[Path] = []

        def _log(msg: str) -> None:
            logs.append(msg)
            self._log(on_log, msg)

        _log(f"[desktop] Parallel build: framework={fw} targets={effective_targets}")

        flags_per_target = {}
        for t in effective_targets:
            flags = self._electron_builder_flags([t])
            if flags and flags != ["--linux"] or t.lower() == "linux":
                flags_per_target[t] = flags[0]

        if not flags_per_target:
            flags_per_target = {"linux": "--linux"}

        results: dict[str, tuple[int, str, str]] = {}

        def _build_one(target_name: str, flag: str) -> tuple[str, int, str, str]:
            cmd = f"npx electron-builder {flag}"
            rc, stdout, stderr = self._run_shell(cmd, cwd=sandbox_path, env=env)
            return target_name, rc, stdout, stderr

        with ThreadPoolExecutor(max_workers=min(max_workers, len(flags_per_target))) as pool:
            futures = {
                pool.submit(_build_one, t, f): t
                for t, f in flags_per_target.items()
            }
            for future in as_completed(futures):
                target_name = futures[future]
                try:
                    name, rc, stdout, stderr = future.result()
                    results[name] = (rc, stdout, stderr)
                    if rc == 0:
                        _log(f"[desktop] ✓ {name} build succeeded")
                    else:
                        _log(f"[desktop] ✗ {name} build failed (exit {rc})")
                except Exception as exc:
                    _log(f"[desktop] ✗ {target_name} build error: {exc}")
                    results[target_name] = (1, "", str(exc))

        elapsed = time.monotonic() - t0
        all_artifacts = self._collect_artifacts(sandbox_path, fw)
        failed = [t for t, (rc, _, _) in results.items() if rc != 0]

        if failed:
            _log(f"[desktop] Parallel build: {len(failed)} target(s) failed: {failed}")
            return BuildResult(
                success=False,
                platform="desktop",
                framework=fw,
                artifacts=all_artifacts,
                output_dir=sandbox_path / "dist",
                message=f"Build failed for targets: {', '.join(failed)}",
                logs=logs,
                build_cmd=f"npx electron-builder (parallel: {list(flags_per_target.values())})",
                elapsed_seconds=elapsed,
            )

        _log(f"[desktop] Parallel build OK – {len(all_artifacts)} artifact(s) in {elapsed:.1f}s")
        return BuildResult(
            success=True,
            platform="desktop",
            framework=fw,
            artifacts=all_artifacts,
            output_dir=sandbox_path / "dist",
            message=f"Desktop parallel build succeeded ({len(all_artifacts)} artifacts)",
            logs=logs,
            build_cmd=f"npx electron-builder (parallel: {list(flags_per_target.values())})",
            elapsed_seconds=elapsed,
        )

    @staticmethod
    def _collect_artifacts(sandbox_path: Path, framework: str) -> list[Path]:
        patterns = {
            "electron": ["dist/*.AppImage", "dist/*.exe", "dist/*.dmg", "dist/*.snap"],
            "tauri": ["src-tauri/target/release/bundle/**/*"],
            "pyinstaller": ["dist/*"],
            "tkinter": ["dist/*"],
            "pyqt": ["dist/*"],
            "flutter": ["build/linux/**/*"],
        }
        globs = patterns.get(framework, ["dist/*", "build/*"])
        found: list[Path] = []
        for g in globs:
            found.extend(p for p in sandbox_path.glob(g) if p.is_file())
        return found
