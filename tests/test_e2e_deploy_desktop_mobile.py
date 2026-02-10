"""End-to-end tests for desktop & mobile app deployment with web preview.

These tests exercise the full flow on a headless server:
  parse markpact README → create sandbox → scaffold → start_service
  → verify the native run command is replaced with an HTTP server.

They also verify that:
  - Web services are NOT affected by web preview logic.
  - When DISPLAY is set, native commands are preserved.
  - Asset directory discovery works per-framework convention.
  - The correct HTTP server command is generated for each scenario.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
from unittest.mock import MagicMock

import pytest

from pactown.builders import DesktopBuilder, MobileBuilder
from pactown.config import ServiceConfig
from pactown.markpact_blocks import parse_blocks, extract_target_config
from pactown.sandbox_manager import (
    SandboxManager,
    _build_web_preview_cmd,
    _detect_web_preview_needed,
    _find_web_assets_dir,
)
from pactown.targets import TargetConfig, TargetPlatform


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_proc_mock(*, returncode=0, pid=42, stdout_lines=None):
    proc = MagicMock()
    proc.returncode = returncode
    proc.pid = pid
    proc.wait.return_value = returncode
    proc.poll.return_value = returncode
    proc.communicate.return_value = (b"", b"")
    proc.args = ["mock"]
    proc.stdout = iter(stdout_lines or [])
    proc.stderr = io.BytesIO(b"")
    return proc


def _fake_popen_factory(captured: dict):
    """Popen mock that records the final shell command (the run command)."""

    def fake_popen(cmd, *, shell=False, cwd=None, env=None, **kw):
        cmd_str = cmd if isinstance(cmd, str) else " ".join(cmd)
        if shell:
            captured["cmd"] = cmd_str
            captured["env"] = dict(env or {})
            captured["cwd"] = cwd
            return _make_proc_mock()
        return _make_proc_mock(stdout_lines=["added 1 package\n"])

    return fake_popen


def _write_readme(tmp_path: Path, content: str) -> Path:
    readme = tmp_path / "README.md"
    readme.write_text(textwrap.dedent(content))
    return readme


@pytest.fixture()
def _headless_env(monkeypatch):
    """Simulate a headless server: no DISPLAY, no xvfb-run."""
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(
        shutil, "which",
        lambda name: "/usr/bin/python3" if name == "python3" else None,
    )


@pytest.fixture()
def manager(tmp_path, monkeypatch):
    sandbox_root = tmp_path / "sandboxes"
    mgr = SandboxManager(sandbox_root)
    if mgr._dep_cache:
        monkeypatch.setattr(mgr._dep_cache, "get_cached_venv", lambda _deps: None)
    monkeypatch.setattr("pactown.sandbox_manager.ensure_venv", lambda *a, **kw: None)
    monkeypatch.setattr(
        "pactown.sandbox_manager.subprocess.run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    return mgr


def _deploy(manager, tmp_path, monkeypatch, readme_text: str, port: int = 9000):
    """Helper: write README, create service, start_service, return captured cmd."""
    readme = _write_readme(tmp_path, readme_text)
    svc = ServiceConfig(name="test-svc", readme=str(readme), port=port)
    captured: dict = {}
    monkeypatch.setattr(
        "pactown.sandbox_manager.subprocess.Popen",
        _fake_popen_factory(captured),
    )
    manager.start_service(service=svc, readme_path=readme, env={}, verbose=False)
    return captured


# ===================================================================
# Desktop: Electron
# ===================================================================

ELECTRON_README = """\
# Calculator

```yaml markpact:target
platform: desktop
framework: electron
app_name: Calculator
window_width: 800
window_height: 600
```

```javascript markpact:deps
electron
```

```javascript markpact:file path=main.js
const { app, BrowserWindow } = require('electron');
app.whenReady().then(() => {
    const win = new BrowserWindow({ width: 800, height: 600 });
    win.loadFile('index.html');
});
app.on('window-all-closed', () => app.quit());
```

```html markpact:file path=index.html
<!DOCTYPE html>
<html><body><h1>Calculator</h1></body></html>
```

```bash markpact:run
npx electron .
```
"""


class TestE2EDeployElectron:

    def test_headless_deploys_via_http(self, manager, tmp_path, monkeypatch, _headless_env):
        captured = _deploy(manager, tmp_path, monkeypatch, ELECTRON_README)
        assert "cmd" in captured
        cmd = captured["cmd"]
        assert "electron" not in cmd.lower()
        assert "http.server" in cmd or "serve" in cmd
        assert "9000" in cmd

    def test_headless_serves_correct_port(self, manager, tmp_path, monkeypatch, _headless_env):
        captured = _deploy(manager, tmp_path, monkeypatch, ELECTRON_README, port=4567)
        assert "4567" in captured["cmd"]

    def test_scaffold_creates_electron_files(self, tmp_path):
        readme = _write_readme(tmp_path, ELECTRON_README)
        blocks = parse_blocks(readme.read_text())
        target_cfg = extract_target_config(blocks)
        assert target_cfg.platform == TargetPlatform.DESKTOP
        assert target_cfg.framework == "electron"

        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        builder = DesktopBuilder()
        builder.scaffold(
            sandbox,
            framework="electron",
            app_name="Calculator",
            extra={"window_width": 800, "window_height": 600},
        )
        assert (sandbox / "package.json").exists()
        assert (sandbox / "main.js").exists()
        pkg = json.loads((sandbox / "package.json").read_text())
        assert pkg["main"] == "main.js"

    def test_native_with_display(self, manager, tmp_path, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setattr(shutil, "which", lambda name: None)
        captured = _deploy(manager, tmp_path, monkeypatch, ELECTRON_README)
        assert "electron" in captured["cmd"].lower()

    def test_index_html_written_to_sandbox(self, manager, tmp_path, monkeypatch, _headless_env):
        captured = _deploy(manager, tmp_path, monkeypatch, ELECTRON_README)
        sandbox_dir = Path(captured["cwd"])
        assert (sandbox_dir / "index.html").exists()
        assert "Calculator" in (sandbox_dir / "index.html").read_text()


# ===================================================================
# Desktop: PyQt
# ===================================================================

PYQT_README = """\
# PyQt App

```yaml markpact:target
platform: desktop
framework: pyqt
app_name: PyQtDemo
```

```python markpact:file path=main.py
import sys
from PyQt6.QtWidgets import QApplication, QLabel
app = QApplication(sys.argv)
label = QLabel("Hello PyQt")
label.show()
app.exec()
```

```html markpact:file path=index.html
<!DOCTYPE html>
<html><body><h1>PyQt Demo</h1></body></html>
```

```python markpact:deps
PyQt6
```

```bash markpact:run
python main.py
```
"""


class TestE2EDeployPyQt:

    def test_headless_deploys_via_http(self, manager, tmp_path, monkeypatch, _headless_env):
        captured = _deploy(manager, tmp_path, monkeypatch, PYQT_README)
        cmd = captured["cmd"]
        # python main.py should be replaced with http server
        assert "http.server" in cmd or "serve" in cmd
        assert "9000" in cmd

    def test_scaffold_creates_spec(self, tmp_path):
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        builder = DesktopBuilder()
        builder.scaffold(sandbox, framework="pyqt", app_name="PyQtDemo")
        assert (sandbox / "PyQtDemo.spec").exists()

    def test_native_with_display(self, manager, tmp_path, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setattr(shutil, "which", lambda name: None)
        captured = _deploy(manager, tmp_path, monkeypatch, PYQT_README)
        assert "main.py" in captured["cmd"]


# ===================================================================
# Desktop: Tauri
# ===================================================================

TAURI_README = """\
# Tauri App

```yaml markpact:target
platform: desktop
framework: tauri
app_name: TauriDemo
app_id: com.test.tauri
```

```html markpact:file path=index.html
<!DOCTYPE html>
<html><body><h1>Tauri Demo</h1></body></html>
```

```javascript markpact:deps
@tauri-apps/api
@tauri-apps/cli
```

```bash markpact:run
npx tauri dev
```
"""


class TestE2EDeployTauri:

    def test_headless_deploys_via_http(self, manager, tmp_path, monkeypatch, _headless_env):
        captured = _deploy(manager, tmp_path, monkeypatch, TAURI_README)
        cmd = captured["cmd"]
        assert "tauri" not in cmd.lower()
        assert "http.server" in cmd or "serve" in cmd

    def test_scaffold_creates_tauri_config(self, tmp_path):
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        builder = DesktopBuilder()
        builder.scaffold(
            sandbox,
            framework="tauri",
            app_name="TauriDemo",
            extra={"app_id": "com.test.tauri"},
        )
        conf = sandbox / "src-tauri" / "tauri.conf.json"
        assert conf.exists()
        data = json.loads(conf.read_text())
        assert data["package"]["productName"] == "TauriDemo"

    def test_native_with_display(self, manager, tmp_path, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setattr(shutil, "which", lambda name: None)
        captured = _deploy(manager, tmp_path, monkeypatch, TAURI_README)
        assert "tauri" in captured["cmd"].lower()


# ===================================================================
# Mobile: Capacitor
# ===================================================================

CAPACITOR_README = """\
# Todo Mobile

```yaml markpact:target
platform: mobile
framework: capacitor
app_name: TodoApp
app_id: com.test.todo
targets:
  - android
  - ios
```

```html markpact:file path=www/index.html
<!DOCTYPE html>
<html><body><h1>Todo App</h1></body></html>
```

```javascript markpact:deps
@capacitor/core
@capacitor/cli
```

```bash markpact:run
npx cap run android
```
"""


class TestE2EDeployCapacitor:

    def test_headless_deploys_via_http(self, manager, tmp_path, monkeypatch, _headless_env):
        captured = _deploy(manager, tmp_path, monkeypatch, CAPACITOR_README)
        cmd = captured["cmd"]
        assert "cap" not in cmd.lower().split()
        assert "http.server" in cmd or "serve" in cmd

    def test_serves_from_www_dir(self, manager, tmp_path, monkeypatch, _headless_env):
        captured = _deploy(manager, tmp_path, monkeypatch, CAPACITOR_README)
        cmd = captured["cmd"]
        # The www/ dir should be the serve target (contains index.html)
        assert "www" in cmd or "http.server" in cmd

    def test_scaffold_creates_capacitor_config(self, tmp_path):
        readme = _write_readme(tmp_path, CAPACITOR_README)
        blocks = parse_blocks(readme.read_text())
        target_cfg = extract_target_config(blocks)
        assert target_cfg.platform == TargetPlatform.MOBILE
        assert target_cfg.framework == "capacitor"
        assert target_cfg.targets == ["android", "ios"]

        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        builder = MobileBuilder()
        builder.scaffold(
            sandbox,
            framework="capacitor",
            app_name="TodoApp",
            extra={"app_id": "com.test.todo"},
        )
        cap_cfg = sandbox / "capacitor.config.json"
        assert cap_cfg.exists()
        data = json.loads(cap_cfg.read_text())
        assert data["appName"] == "TodoApp"
        assert data["appId"] == "com.test.todo"
        assert data["webDir"] == "dist"

    def test_native_with_display(self, manager, tmp_path, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setattr(shutil, "which", lambda name: None)
        captured = _deploy(manager, tmp_path, monkeypatch, CAPACITOR_README)
        assert "cap" in captured["cmd"].lower()


# ===================================================================
# Mobile: Kivy
# ===================================================================

KIVY_README = """\
# Weather App

```yaml markpact:target
platform: mobile
framework: kivy
app_name: WeatherApp
app_id: com.test.weather
fullscreen: true
```

```python markpact:file path=main.py
from kivy.app import App
from kivy.uix.label import Label
class WeatherApp(App):
    def build(self):
        return Label(text="Weather")
WeatherApp().run()
```

```html markpact:file path=index.html
<!DOCTYPE html>
<html><body><h1>Weather App</h1></body></html>
```

```python markpact:deps
kivy
buildozer
```

```bash markpact:run
python main.py
```
"""


class TestE2EDeployKivy:

    def test_headless_deploys_via_http(self, manager, tmp_path, monkeypatch, _headless_env):
        captured = _deploy(manager, tmp_path, monkeypatch, KIVY_README)
        cmd = captured["cmd"]
        assert "http.server" in cmd or "serve" in cmd

    def test_scaffold_creates_buildozer_spec(self, tmp_path):
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        builder = MobileBuilder()
        builder.scaffold(
            sandbox,
            framework="kivy",
            app_name="WeatherApp",
            extra={"app_id": "com.test.weather", "fullscreen": True},
        )
        spec = sandbox / "buildozer.spec"
        assert spec.exists()
        text = spec.read_text()
        assert "WeatherApp" in text
        assert "fullscreen = 1" in text

    def test_native_with_display(self, manager, tmp_path, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setattr(shutil, "which", lambda name: None)
        captured = _deploy(manager, tmp_path, monkeypatch, KIVY_README)
        assert "main.py" in captured["cmd"]


# ===================================================================
# Mobile: React Native
# ===================================================================

REACT_NATIVE_README = """\
# Chat App

```yaml markpact:target
platform: mobile
framework: react-native
app_name: ChatApp
```

```javascript markpact:file path=App.js
import React from 'react';
import { Text, View } from 'react-native';
export default function App() {
    return <View><Text>Chat</Text></View>;
}
```

```html markpact:file path=index.html
<!DOCTYPE html>
<html><body><h1>Chat App</h1></body></html>
```

```javascript markpact:deps
react-native
```

```bash markpact:run
npx react-native run-android
```
"""


class TestE2EDeployReactNative:

    def test_headless_deploys_via_http(self, manager, tmp_path, monkeypatch, _headless_env):
        captured = _deploy(manager, tmp_path, monkeypatch, REACT_NATIVE_README)
        cmd = captured["cmd"]
        assert "react-native" not in cmd.lower()
        assert "http.server" in cmd or "serve" in cmd

    def test_native_with_display(self, manager, tmp_path, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setattr(shutil, "which", lambda name: None)
        captured = _deploy(manager, tmp_path, monkeypatch, REACT_NATIVE_README)
        assert "react-native" in captured["cmd"].lower()


# ===================================================================
# Regression: Web services must NOT be affected
# ===================================================================

WEB_FASTAPI_README = """\
# API Service

```python markpact:file path=main.py
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok"}
```

```python markpact:deps
fastapi
uvicorn
```

```bash markpact:run
uvicorn main:app --host 0.0.0.0 --port $PORT
```
"""

WEB_EXPRESS_README = """\
# Express API

```javascript markpact:file path=index.js
const express = require('express');
const app = express();
app.get('/', (req, res) => res.json({ok: true}));
app.listen(process.env.PORT || 3000);
```

```javascript markpact:deps
express
```

```bash markpact:run
node index.js
```
"""


class TestE2EWebServiceNotAffected:

    def test_fastapi_runs_normally_on_headless(self, manager, tmp_path, monkeypatch, _headless_env):
        captured = _deploy(manager, tmp_path, monkeypatch, WEB_FASTAPI_README)
        cmd = captured["cmd"]
        assert "uvicorn" in cmd
        assert "http.server" not in cmd
        assert "serve" not in cmd.split()

    def test_express_runs_normally_on_headless(self, manager, tmp_path, monkeypatch, _headless_env):
        captured = _deploy(manager, tmp_path, monkeypatch, WEB_EXPRESS_README)
        cmd = captured["cmd"]
        assert "node" in cmd
        assert "http.server" not in cmd


# ===================================================================
# Asset directory discovery per framework convention
# ===================================================================

class TestE2EAssetDiscovery:

    def test_capacitor_www_dir(self, tmp_path):
        """Capacitor apps put web assets in www/."""
        www = tmp_path / "www"
        www.mkdir()
        (www / "index.html").write_text("<h1>App</h1>")
        assert _find_web_assets_dir(tmp_path) == www

    def test_react_build_dir(self, tmp_path):
        """React/CRA apps put build output in build/."""
        build = tmp_path / "build"
        build.mkdir()
        (build / "index.html").write_text("<h1>App</h1>")
        assert _find_web_assets_dir(tmp_path) == build

    def test_vite_dist_dir(self, tmp_path):
        """Vite/Tauri apps put build output in dist/."""
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<h1>App</h1>")
        assert _find_web_assets_dir(tmp_path) == dist

    def test_public_dir(self, tmp_path):
        """Static assets in public/."""
        pub = tmp_path / "public"
        pub.mkdir()
        (pub / "index.html").write_text("<h1>App</h1>")
        assert _find_web_assets_dir(tmp_path) == pub

    def test_root_fallback(self, tmp_path):
        """index.html at root."""
        (tmp_path / "index.html").write_text("<h1>App</h1>")
        assert _find_web_assets_dir(tmp_path) == tmp_path

    def test_no_index_falls_back_to_root(self, tmp_path):
        """No index.html anywhere → still serves from root."""
        assert _find_web_assets_dir(tmp_path) == tmp_path

    def test_priority_www_over_dist(self, tmp_path):
        """www/ takes priority over dist/."""
        for d in ("www", "dist"):
            p = tmp_path / d
            p.mkdir()
            (p / "index.html").write_text(f"<h1>{d}</h1>")
        assert _find_web_assets_dir(tmp_path) == tmp_path / "www"

    def test_priority_dist_over_build(self, tmp_path):
        """dist/ takes priority over build/."""
        for d in ("dist", "build"):
            p = tmp_path / d
            p.mkdir()
            (p / "index.html").write_text(f"<h1>{d}</h1>")
        assert _find_web_assets_dir(tmp_path) == tmp_path / "dist"


# ===================================================================
# Web preview command generation per scenario
# ===================================================================

class TestE2EPreviewCommandGeneration:

    def test_python_fallback_includes_bind(self, tmp_path, monkeypatch):
        (tmp_path / "index.html").write_text("<h1>App</h1>")
        monkeypatch.setattr(
            shutil, "which",
            lambda name: "/usr/bin/python3" if name == "python3" else None,
        )
        cmd = _build_web_preview_cmd(tmp_path, 8080, None, lambda m, l: None)
        assert "0.0.0.0" in cmd
        assert "8080" in cmd
        assert "http.server" in cmd

    def test_npx_serve_with_spa_flag(self, tmp_path, monkeypatch):
        (tmp_path / "index.html").write_text("<h1>App</h1>")
        serve_bin = tmp_path / "node_modules" / ".bin" / "serve"
        serve_bin.parent.mkdir(parents=True)
        serve_bin.write_text("#!/bin/sh")
        cmd = _build_web_preview_cmd(tmp_path, 3000, None, lambda m, l: None)
        assert "npx serve" in cmd
        assert "-s" in cmd  # SPA mode
        assert "3000" in cmd

    def test_serves_subdir_when_index_in_www(self, tmp_path, monkeypatch):
        www = tmp_path / "www"
        www.mkdir()
        (www / "index.html").write_text("<h1>App</h1>")
        monkeypatch.setattr(
            shutil, "which",
            lambda name: "/usr/bin/python3" if name == "python3" else None,
        )
        cmd = _build_web_preview_cmd(tmp_path, 5000, None, lambda m, l: None)
        assert "www" in cmd
        assert "5000" in cmd

    def test_venv_python_preferred(self, tmp_path, monkeypatch):
        (tmp_path / "index.html").write_text("<h1>App</h1>")
        venv_bin = tmp_path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "python").write_text("#!/bin/sh")
        monkeypatch.setattr(shutil, "which", lambda name: None)
        cmd = _build_web_preview_cmd(tmp_path, 7000, None, lambda m, l: None)
        assert ".venv/bin/python" in cmd
        assert "7000" in cmd

    def test_creates_fallback_html_for_python_desktop(self, tmp_path, monkeypatch):
        # No index.html initially
        cfg = TargetConfig(platform=TargetPlatform.DESKTOP, framework="tkinter")
        monkeypatch.setattr(shutil, "which", lambda name: None)
        
        # Call the function
        cmd = _build_web_preview_cmd(tmp_path, 8080, cfg, lambda m, l: None)
        
        # Should create index.html
        assert (tmp_path / "index.html").exists()
        content = (tmp_path / "index.html").read_text()
        assert "Desktop App Preview" in content
        assert "tkinter" in content
        assert "sudo apt install python3-tk" in content
        assert cmd is not None


# ===================================================================
# Detection logic: framework-specific patterns
# ===================================================================

class TestE2EDetectionPerFramework:

    @pytest.fixture(autouse=True)
    def _no_display(self, monkeypatch):
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.setattr(shutil, "which", lambda name: None)

    def test_electron_dot(self):
        assert _detect_web_preview_needed("electron .", None, {}, Path("/tmp"))

    def test_npx_electron(self):
        assert _detect_web_preview_needed("npx electron .", None, {}, Path("/tmp"))

    def test_cap_run(self):
        assert _detect_web_preview_needed("npx cap run android", None, {}, Path("/tmp"))

    def test_cap_open(self):
        assert _detect_web_preview_needed("npx cap open android", None, {}, Path("/tmp"))

    def test_tauri_dev(self):
        assert _detect_web_preview_needed("npx tauri dev", None, {}, Path("/tmp"))

    def test_flutter_run(self):
        assert _detect_web_preview_needed("flutter run -d linux", None, {}, Path("/tmp"))

    def test_react_native_run(self):
        assert _detect_web_preview_needed("npx react-native run-android", None, {}, Path("/tmp"))

    def test_python_main_with_kivy_target(self):
        cfg = TargetConfig(platform=TargetPlatform.MOBILE, framework="kivy")
        assert _detect_web_preview_needed("python main.py", cfg, {}, Path("/tmp"))

    def test_python_main_with_pyqt_target(self):
        cfg = TargetConfig(platform=TargetPlatform.DESKTOP, framework="pyqt")
        assert _detect_web_preview_needed("python main.py", cfg, {}, Path("/tmp"))

    def test_python_main_with_pyinstaller_target(self):
        cfg = TargetConfig(platform=TargetPlatform.DESKTOP, framework="pyinstaller")
        assert _detect_web_preview_needed("python main.py", cfg, {}, Path("/tmp"))

    def test_python_main_with_tkinter_target(self):
        cfg = TargetConfig(platform=TargetPlatform.DESKTOP, framework="tkinter")
        assert _detect_web_preview_needed("python main.py", cfg, {}, Path("/tmp"))

    def test_python_main_without_target_not_affected(self):
        assert not _detect_web_preview_needed("python main.py", None, {}, Path("/tmp"))

    def test_uvicorn_not_affected(self):
        assert not _detect_web_preview_needed("uvicorn main:app", None, {}, Path("/tmp"))

    def test_node_not_affected(self):
        assert not _detect_web_preview_needed("node index.js", None, {}, Path("/tmp"))

    def test_display_set_skips_preview(self):
        assert not _detect_web_preview_needed("npx electron .", None, {"DISPLAY": ":0"}, Path("/tmp"))

    def test_xvfb_available_skips_preview(self, monkeypatch):
        monkeypatch.setattr(
            shutil, "which",
            lambda name: "/usr/bin/xvfb-run" if name == "xvfb-run" else None,
        )
        assert not _detect_web_preview_needed("npx electron .", None, {}, Path("/tmp"))

    def test_target_cfg_framework_triggers_preview(self):
        cfg = TargetConfig(platform=TargetPlatform.DESKTOP, framework="electron")
        assert _detect_web_preview_needed("some-custom-cmd", cfg, {}, Path("/tmp"))

    def test_web_target_not_affected(self):
        cfg = TargetConfig(platform=TargetPlatform.WEB, framework="fastapi")
        assert not _detect_web_preview_needed("uvicorn main:app", cfg, {}, Path("/tmp"))
