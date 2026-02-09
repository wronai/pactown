"""Builder for mobile applications (Capacitor, React Native, Flutter, Kivy)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Optional

from .base import Builder, BuildError, BuildResult


class MobileBuilder(Builder):
    """Builds mobile application artifacts from a markpact sandbox."""

    @property
    def platform_name(self) -> str:
        return "mobile"

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
        if fw == "capacitor":
            self._scaffold_capacitor(sandbox_path, app_name=app_name, extra=extra, on_log=on_log)
        elif fw == "react-native":
            self._scaffold_react_native(sandbox_path, app_name=app_name, extra=extra, on_log=on_log)
        elif fw == "kivy":
            self._scaffold_kivy(sandbox_path, app_name=app_name, extra=extra, on_log=on_log)
        elif fw == "flutter":
            self._log(on_log, "[mobile] Flutter scaffolding – using files as-is (run `flutter create` if needed)")
        else:
            self._log(on_log, f"[mobile] No scaffolding for framework '{fw}' – using files as-is")

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
        effective_targets = targets or ["android"]
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
                cmd = self._default_build_cmd(fw, effective_targets)

        if not cmd:
            return BuildResult(
                success=False,
                platform="mobile",
                framework=fw,
                message="No build command specified and no default known for this framework",
                logs=logs,
            )

        _log(f"[mobile] Building with framework={fw} targets={effective_targets}")
        _log(f"[mobile] $ {cmd}")

        rc, stdout, stderr = self._run_shell(cmd, cwd=sandbox_path, env=env, on_log=on_log)

        elapsed = time.monotonic() - t0

        if rc != 0:
            _log(f"[mobile] Build failed (exit {rc})")
            if stderr:
                _log(f"[mobile] STDERR: {stderr[:2000]}")
            return BuildResult(
                success=False,
                platform="mobile",
                framework=fw,
                message=f"Build failed with exit code {rc}",
                logs=logs,
                build_cmd=cmd,
                elapsed_seconds=elapsed,
            )

        artifacts = self._collect_artifacts(sandbox_path, fw)
        _log(f"[mobile] Build OK – {len(artifacts)} artifact(s) in {elapsed:.1f}s")

        return BuildResult(
            success=True,
            platform="mobile",
            framework=fw,
            artifacts=artifacts,
            output_dir=sandbox_path,
            message=f"Mobile build succeeded ({len(artifacts)} artifacts)",
            logs=logs,
            build_cmd=cmd,
            elapsed_seconds=elapsed,
        )

    # ------------------------------------------------------------------
    # Scaffolding helpers
    # ------------------------------------------------------------------

    def _scaffold_capacitor(
        self,
        sandbox_path: Path,
        *,
        app_name: str,
        extra: Optional[dict[str, Any]],
        on_log: Optional[Callable[[str], None]],
    ) -> None:
        self._log(on_log, "[mobile] Scaffolding Capacitor app")

        # capacitor.config.json
        cap_cfg = sandbox_path / "capacitor.config.json"
        if not cap_cfg.exists():
            config = {
                "appId": (extra or {}).get("app_id", f"com.pactown.{app_name}"),
                "appName": app_name,
                "webDir": "dist",
                "bundledWebRuntime": False,
                "server": {
                    "androidScheme": "https",
                },
            }
            cap_cfg.write_text(json.dumps(config, indent=2))

        # Ensure package.json has capacitor scripts
        pkg_json = sandbox_path / "package.json"
        if pkg_json.exists():
            try:
                pkg = json.loads(pkg_json.read_text())
            except Exception:
                pkg = {}
        else:
            pkg = {"name": app_name, "version": "1.0.0"}

        scripts = pkg.setdefault("scripts", {})
        scripts.setdefault("cap:sync", "npx cap sync")
        scripts.setdefault("cap:build:android", "npx cap sync && npx cap build android")
        scripts.setdefault("cap:build:ios", "npx cap sync && npx cap build ios")
        pkg_json.write_text(json.dumps(pkg, indent=2))

    def _scaffold_react_native(
        self,
        sandbox_path: Path,
        *,
        app_name: str,
        extra: Optional[dict[str, Any]],
        on_log: Optional[Callable[[str], None]],
    ) -> None:
        self._log(on_log, "[mobile] Scaffolding React Native app")

        # app.json
        app_json = sandbox_path / "app.json"
        if not app_json.exists():
            config = {
                "name": app_name,
                "displayName": (extra or {}).get("app_name", app_name),
            }
            app_json.write_text(json.dumps(config, indent=2))

    def _scaffold_kivy(
        self,
        sandbox_path: Path,
        *,
        app_name: str,
        extra: Optional[dict[str, Any]],
        on_log: Optional[Callable[[str], None]],
    ) -> None:
        self._log(on_log, "[mobile] Scaffolding Kivy/Buildozer app")

        spec = sandbox_path / "buildozer.spec"
        if not spec.exists():
            app_id = (extra or {}).get("app_id", f"com.pactown.{app_name}")
            icon = (extra or {}).get("icon", "")
            spec.write_text(
                f"""\
[app]
title = {app_name}
package.name = {app_name}
package.domain = {app_id.rsplit('.', 1)[0] if '.' in app_id else 'com.pactown'}
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 1.0.0
requirements = python3,kivy
android.permissions = INTERNET
{'icon.filename = ' + icon if icon else '# icon.filename ='}
orientation = portrait
fullscreen = {'1' if (extra or {}).get('fullscreen') else '0'}

[buildozer]
log_level = 2
warn_on_root = 1
"""
            )

    # ------------------------------------------------------------------
    # Defaults & artifact collection
    # ------------------------------------------------------------------

    @staticmethod
    def _default_build_cmd(framework: str, targets: list[str]) -> str:
        fw = (framework or "").strip().lower()
        target = targets[0] if targets else "android"

        if fw == "capacitor":
            return f"npx cap sync && npx cap build {target}"
        if fw == "react-native":
            if target == "ios":
                return "npx react-native build-ios --mode=release"
            return "npx react-native build-android --mode=release"
        if fw == "flutter":
            if target == "ios":
                return "flutter build ios --release"
            return "flutter build apk --release"
        if fw == "kivy":
            return f"buildozer {target} debug"
        return ""

    @staticmethod
    def _collect_artifacts(sandbox_path: Path, framework: str) -> list[Path]:
        patterns: dict[str, list[str]] = {
            "capacitor": [
                "android/app/build/outputs/apk/**/*.apk",
                "ios/App/build/**/*.ipa",
            ],
            "react-native": [
                "android/app/build/outputs/apk/**/*.apk",
                "ios/build/**/*.ipa",
            ],
            "flutter": [
                "build/app/outputs/flutter-apk/*.apk",
                "build/ios/**/*.ipa",
            ],
            "kivy": [
                "bin/*.apk",
                "bin/*.aab",
            ],
        }
        globs = patterns.get(framework, ["build/**/*.apk", "build/**/*.ipa", "bin/*.apk"])
        found: list[Path] = []
        for g in globs:
            found.extend(p for p in sandbox_path.glob(g) if p.is_file())
        return found
