"""Builder for mobile applications (Capacitor, React Native, Flutter, Kivy)."""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Optional

from .base import Builder, BuildError, BuildResult

try:
    from ..nfo_config import logged, get_logger
except Exception:
    def logged(cls=None, **kw):  # type: ignore[misc]
        return cls if cls is not None else lambda c: c
    import logging as _logging
    get_logger = _logging.getLogger

_logger = get_logger("pactown.builders.mobile")


def _sanitize_java_package_id(raw: str) -> str:
    """Sanitize a string into a valid Java package identifier.

    Java package segments must match ``[a-zA-Z_][a-zA-Z0-9_]*`` and the
    full ID uses dots as separators (e.g. ``com.example.myapp``).
    Dashes and other illegal characters are replaced with underscores;
    segments that start with a digit get a leading underscore.
    """
    # Replace any char that is not alphanumeric, underscore, or dot
    sanitized = re.sub(r"[^a-zA-Z0-9_.]", "_", raw)
    # Collapse consecutive underscores
    sanitized = re.sub(r"_+", "_", sanitized)
    # Ensure each segment doesn't start with a digit
    parts = sanitized.split(".")
    cleaned: list[str] = []
    for part in parts:
        part = part.strip("_")  # trim leading/trailing underscores
        if not part:
            continue
        if part[0].isdigit():
            part = f"_{part}"
        cleaned.append(part)
    return ".".join(cleaned) if cleaned else "com.pactown.app"


# Deprecated Capacitor plugins → their replacements (name change in Cap 5+).
_CAP_DEPRECATED_PLUGINS: dict[str, str] = {
    "@capacitor/storage": "@capacitor/preferences",
}


@logged
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

        # Capacitor: ensure platforms are added before sync/build.
        # `npx cap sync` fails if the platform dir (android/, ios/) doesn't exist.
        if fw == "capacitor":
            self._ensure_cap_platforms(sandbox_path, effective_targets, env=env, on_log=_log)

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

    # Capacitor packages that must be present for `npx cap` to work.
    # Pin to 6.x – compatible with Node >=18.  Capacitor 7.x needs >=20,
    # 8.x needs >=22; many runners still use Node 20 LTS.
    _CAP_REQUIRED_DEPS: dict[str, str] = {
        "@capacitor/cli": "^6.0.0",
        "@capacitor/core": "^6.0.0",
    }
    # Common Capacitor plugins with versions compatible with @capacitor/core@^6.0.0
    _CAP_PLUGIN_DEPS: dict[str, str] = {
        "@capacitor/preferences": "^6.0.0",
        "@capacitor/camera": "^6.0.0",
        "@capacitor/geolocation": "^6.0.0",
        "@capacitor/network": "^6.0.0",
        "@capacitor/device": "^6.0.0",
        "@capacitor/app": "^6.0.0",
        "@capacitor/haptics": "^6.0.0",
        "@capacitor/keyboard": "^6.0.0",
        "@capacitor/status-bar": "^6.0.0",
        "@capacitor/splash-screen": "^6.0.0",
    }
    _CAP_PLATFORM_DEPS: dict[str, str] = {
        "android": "@capacitor/android",
        "ios": "@capacitor/ios",
    }

    def _scaffold_capacitor(
        self,
        sandbox_path: Path,
        *,
        app_name: str,
        extra: Optional[dict[str, Any]],
        on_log: Optional[Callable[[str], None]],
    ) -> None:
        self._log(on_log, "[mobile] Scaffolding Capacitor app")

        # Detect webDir: use "dist" if dist/index.html exists, "." if
        # index.html is at root, otherwise default to "dist" and copy
        # web assets there so `cap sync` can find them.
        web_dir = self._resolve_cap_web_dir(sandbox_path, on_log=on_log)

        # capacitor.config.json
        cap_cfg = sandbox_path / "capacitor.config.json"
        if not cap_cfg.exists():
            raw_id = (extra or {}).get("app_id", f"com.pactown.{app_name}")
            config = {
                "appId": _sanitize_java_package_id(raw_id),
                "appName": app_name,
                "webDir": web_dir,
                "server": {
                    "androidScheme": "https",
                },
            }
            cap_cfg.write_text(json.dumps(config, indent=2))
        else:
            # Update webDir in existing config if it still points to "dist"
            # but web assets are elsewhere.
            try:
                existing = json.loads(cap_cfg.read_text())
                if existing.get("webDir") == "dist" and web_dir != "dist":
                    existing["webDir"] = web_dir
                    cap_cfg.write_text(json.dumps(existing, indent=2))
            except Exception:
                pass

        # Ensure package.json has capacitor scripts and required deps
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

        # Ensure @capacitor/cli and @capacitor/core are in dependencies.
        # Also pin "latest" → "^6.0.0" because _ensure_package_json may
        # have written "latest" before scaffold, and Capacitor 8.x needs
        # Node >=22 which many runners don't have yet.
        deps = pkg.setdefault("dependencies", {})
        for name, version in self._CAP_REQUIRED_DEPS.items():
            if name not in deps or deps[name] == "latest":
                deps[name] = version

        # Ensure platform packages are in dependencies based on targets
        targets = (extra or {}).get("targets") or ["android"]
        for target in targets:
            platform_pkg = self._CAP_PLATFORM_DEPS.get(target)
            if platform_pkg:
                # Always use compatible version with core (6.x) to prevent conflicts
                deps[platform_pkg] = "^6.0.0"

        # Update any existing Capacitor plugin dependencies to compatible versions
        # to prevent version conflicts like @capacitor/storage@1.2.5 with @capacitor/core@^6.0.0
        for plugin_name, compatible_version in self._CAP_PLUGIN_DEPS.items():
            if plugin_name in deps and deps[plugin_name] == "latest":
                deps[plugin_name] = compatible_version

        # Migrate deprecated Capacitor plugins to their replacements.
        # e.g. @capacitor/storage → @capacitor/preferences (renamed in Cap 5+).
        for old_name, new_name in _CAP_DEPRECATED_PLUGINS.items():
            if old_name in deps:
                old_ver = deps.pop(old_name)
                new_ver = self._CAP_PLUGIN_DEPS.get(new_name, "^6.0.0")
                deps.setdefault(new_name, new_ver)
                _logger.info(
                    "[mobile] Migrated deprecated %s → %s (%s)",
                    old_name, new_name, new_ver,
                )

        # Catch-all: pin ANY remaining @capacitor/* dep that is "latest" to ^6.0.0
        # to prevent ERESOLVE when npm resolves "latest" to a newer major.
        for dep_name in list(deps):
            if dep_name.startswith("@capacitor/") and deps[dep_name] == "latest":
                deps[dep_name] = "^6.0.0"

        pkg_json.write_text(json.dumps(pkg, indent=2))

        # Write .npmrc with legacy-peer-deps so that *any* npm install
        # in this sandbox (including the build command itself) tolerates
        # peer-dependency mismatches that Capacitor ecosystem often has.
        npmrc = sandbox_path / ".npmrc"
        if not npmrc.exists():
            npmrc.write_text("legacy-peer-deps=true\n")

    @staticmethod
    def _resolve_cap_web_dir(
        sandbox_path: Path,
        *,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Determine the correct webDir for capacitor.config.json.

        Checks common build output dirs first, then falls back to root.
        If index.html is only at root, returns "." so Capacitor can find it.
        """
        for candidate in ("dist", "build", "www", "public"):
            if (sandbox_path / candidate / "index.html").is_file():
                return candidate
        if (sandbox_path / "index.html").is_file():
            return "."
        # No index.html found yet – default to "dist" (will be created by
        # a build step or the user's own tooling).
        return "dist"

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
            app_id = _sanitize_java_package_id(
                (extra or {}).get("app_id", f"com.pactown.{app_name}")
            )
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
    # Platform bootstrapping
    # ------------------------------------------------------------------

    def _ensure_cap_platforms(
        self,
        sandbox_path: Path,
        targets: list[str],
        *,
        env: Optional[dict[str, str]] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Run ``npx cap add <platform>`` for each target whose directory is missing.

        Capacitor requires the native platform project (``android/``, ``ios/``)
        to exist before ``npx cap sync`` can work.  The scaffold step creates
        ``capacitor.config.json`` and installs npm deps, but the actual native
        project is generated by ``npx cap add``.
        """
        for target in targets:
            platform_dir = sandbox_path / target
            if platform_dir.is_dir():
                _logger.debug("[mobile] Platform dir already exists: %s", target)
                continue

            add_cmd = f"npx cap add {target}"
            if on_log:
                on_log(f"[mobile] Adding Capacitor platform: {add_cmd}")
            _logger.info("[mobile] Running: %s", add_cmd)

            rc, stdout, stderr = self._run_shell(
                add_cmd, cwd=sandbox_path, env=env, on_log=on_log, timeout=120,
            )
            if rc != 0:
                _logger.warning(
                    "[mobile] `%s` failed (exit %d) – build may fail", add_cmd, rc,
                )
                if on_log:
                    on_log(f"[mobile] Warning: {add_cmd} failed (exit {rc})")
            else:
                _logger.info("[mobile] Platform '%s' added successfully", target)

    # ------------------------------------------------------------------
    # Defaults & artifact collection
    # ------------------------------------------------------------------

    @staticmethod
    def _default_build_cmd(framework: str, targets: list[str]) -> str:
        fw = (framework or "").strip().lower()
        target = targets[0] if targets else "android"

        if fw == "capacitor":
            if target == "ios":
                return "npx cap sync ios && cd ios/App && xcodebuild -workspace App.xcworkspace -scheme App -configuration Debug -sdk iphonesimulator build"
            return f"npx cap sync {target} && cd {target} && ./gradlew assembleDebug"
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
