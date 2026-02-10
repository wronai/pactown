"""Builder for desktop applications (Electron, Tauri, PyInstaller, Tkinter, PyQt)."""

from __future__ import annotations

import json
import time
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
            from ..targets import get_framework_meta
            meta = get_framework_meta(fw)
            if meta and meta.default_build_cmd:
                cmd = meta.default_build_cmd
            else:
                cmd = self._default_build_cmd(fw, targets)

        if not cmd:
            return BuildResult(
                success=False,
                platform="desktop",
                framework=fw,
                message="No build command specified and no default known for this framework",
                logs=logs,
            )

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

    def _scaffold_electron(
        self,
        sandbox_path: Path,
        *,
        app_name: str,
        extra: Optional[dict[str, Any]],
        on_log: Optional[Callable[[str], None]],
    ) -> None:
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
                    "build": "electron-builder --linux --windows --mac",
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
                    "build": "electron-builder --linux --windows --mac",
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
        dev_deps = pkg.setdefault("devDependencies", {})
        added = False
        for name in ("electron", "electron-builder"):
            if name not in dev_deps:
                dev_deps[name] = "latest"
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
    def _default_build_cmd(framework: str, targets: Optional[list[str]]) -> str:
        fw = (framework or "").strip().lower()
        if fw == "electron":
            return "npx electron-builder --linux"
        if fw == "tauri":
            return "npx tauri build"
        if fw in ("pyinstaller", "tkinter", "pyqt"):
            return "pyinstaller --onefile --windowed main.py"
        if fw == "flutter":
            t = (targets or ["linux"])[0]
            return f"flutter build {t}"
        return ""

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
