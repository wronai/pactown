"""Tests for desktop/mobile web preview mode and helper functions."""
import io
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from pactown.config import ServiceConfig
from pactown.sandbox_manager import (
    SandboxManager,
    _detect_web_preview_needed,
    _build_web_preview_cmd,
    _find_web_assets_dir,
)


ELECTRON_README = """\
# Electron App

```yaml markpact:target
platform: desktop
framework: electron
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
<html><body><h1>Hello</h1></body></html>
```

```bash markpact:run
npx electron .
```
"""


def _make_proc_mock(*, returncode=0, pid=42, stdout_lines=None):
    """Create a process mock with proper int returncode to avoid MagicMock comparison bugs."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.pid = pid
    proc.wait.return_value = returncode
    proc.poll.return_value = returncode
    proc.communicate.return_value = (b"", b"")
    proc.args = ["mock"]
    if stdout_lines is not None:
        proc.stdout = iter(stdout_lines)
    else:
        proc.stdout = iter([])
    proc.stderr = io.BytesIO(b"")
    return proc


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


@pytest.fixture()
def readme_path(tmp_path):
    p = tmp_path / "README.md"
    p.write_text(ELECTRON_README)
    return p


@pytest.fixture()
def service(readme_path):
    return ServiceConfig(name="electron-svc", readme=str(readme_path), port=9000)


def _fake_popen_factory(captured: dict):
    """Return a Popen mock that records the final run command."""

    def fake_popen(cmd, *, shell=False, cwd=None, env=None, **kw):
        cmd_str = cmd if isinstance(cmd, str) else " ".join(cmd)
        if shell:
            captured["cmd"] = cmd_str
            captured["env"] = dict(env or {})
            return _make_proc_mock()
        return _make_proc_mock(stdout_lines=["added 1 package\n"])

    return fake_popen


# ---------------------------------------------------------------------------
# Unit tests for _detect_web_preview_needed
# ---------------------------------------------------------------------------

class TestDetectWebPreviewNeeded:

    def test_electron_cmd_no_display_no_xvfb(self, monkeypatch):
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.setattr(shutil, "which", lambda name: None)
        assert _detect_web_preview_needed("npx electron .", None, {}, Path("/tmp")) is True

    def test_electron_cmd_with_display(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: None)
        assert _detect_web_preview_needed("npx electron .", None, {"DISPLAY": ":0"}, Path("/tmp")) is False

    def test_electron_cmd_with_xvfb(self, monkeypatch):
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/xvfb-run" if name == "xvfb-run" else None)
        assert _detect_web_preview_needed("npx electron .", None, {}, Path("/tmp")) is False

    def test_capacitor_cmd_headless(self, monkeypatch):
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.setattr(shutil, "which", lambda name: None)
        assert _detect_web_preview_needed("npx cap run android", None, {}, Path("/tmp")) is True

    def test_web_cmd_not_affected(self, monkeypatch):
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.setattr(shutil, "which", lambda name: None)
        assert _detect_web_preview_needed("uvicorn main:app --port 8000", None, {}, Path("/tmp")) is False

    def test_python_main_only_native_with_target(self, monkeypatch):
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.setattr(shutil, "which", lambda name: None)
        # Without target config, python main.py is NOT treated as native
        assert _detect_web_preview_needed("python main.py", None, {}, Path("/tmp")) is False

    def test_python_main_native_with_desktop_target(self, monkeypatch):
        from pactown.targets import TargetConfig, TargetPlatform
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.setattr(shutil, "which", lambda name: None)
        cfg = TargetConfig(platform=TargetPlatform.DESKTOP, framework="pyqt")
        assert _detect_web_preview_needed("python main.py", cfg, {}, Path("/tmp")) is True


# ---------------------------------------------------------------------------
# Unit tests for _find_web_assets_dir
# ---------------------------------------------------------------------------

class TestFindWebAssetsDir:

    def test_index_at_root(self, tmp_path):
        (tmp_path / "index.html").write_text("<html></html>")
        assert _find_web_assets_dir(tmp_path) == tmp_path

    def test_www_subdir(self, tmp_path):
        www = tmp_path / "www"
        www.mkdir()
        (www / "index.html").write_text("<html></html>")
        assert _find_web_assets_dir(tmp_path) == www

    def test_dist_subdir(self, tmp_path):
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html></html>")
        assert _find_web_assets_dir(tmp_path) == dist

    def test_fallback_to_root(self, tmp_path):
        assert _find_web_assets_dir(tmp_path) == tmp_path

    def test_www_preferred_over_dist(self, tmp_path):
        for d in ("www", "dist"):
            p = tmp_path / d
            p.mkdir()
            (p / "index.html").write_text("<html></html>")
        assert _find_web_assets_dir(tmp_path) == tmp_path / "www"


# ---------------------------------------------------------------------------
# Unit tests for _build_web_preview_cmd
# ---------------------------------------------------------------------------

class TestBuildWebPreviewCmd:

    def test_fallback_to_python_http_server(self, tmp_path, monkeypatch):
        (tmp_path / "index.html").write_text("<html></html>")
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/python3" if name == "python3" else None)
        logs = []
        cmd = _build_web_preview_cmd(tmp_path, 8080, None, lambda msg, lvl: logs.append(msg))
        assert cmd is not None
        assert "http.server" in cmd
        assert "8080" in cmd
        assert "0.0.0.0" in cmd

    def test_uses_npx_serve_when_available(self, tmp_path, monkeypatch):
        (tmp_path / "index.html").write_text("<html></html>")
        serve_bin = tmp_path / "node_modules" / ".bin" / "serve"
        serve_bin.parent.mkdir(parents=True)
        serve_bin.write_text("#!/bin/sh\nexec serve")
        logs = []
        cmd = _build_web_preview_cmd(tmp_path, 3000, None, lambda msg, lvl: logs.append(msg))
        assert cmd is not None
        assert "npx serve" in cmd
        assert "3000" in cmd


# ---------------------------------------------------------------------------
# Integration: start_service uses web preview on headless server
# ---------------------------------------------------------------------------

class TestWebPreviewIntegration:

    def test_electron_uses_web_preview_on_headless(self, manager, readme_path, service, monkeypatch):
        """On headless server without xvfb, Electron app is served via HTTP."""
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/python3" if name == "python3" else None)

        captured: dict = {}
        monkeypatch.setattr("pactown.sandbox_manager.subprocess.Popen", _fake_popen_factory(captured))

        manager.start_service(service=service, readme_path=readme_path, env={}, verbose=False)

        assert "cmd" in captured, "Popen was never called"
        assert "electron" not in captured["cmd"].lower(), "Should NOT launch electron natively"
        assert "http.server" in captured["cmd"] or "serve" in captured["cmd"]

    def test_electron_runs_natively_with_display(self, manager, readme_path, service, monkeypatch):
        """When DISPLAY is set, Electron runs natively."""
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setattr(shutil, "which", lambda name: None)

        captured: dict = {}
        monkeypatch.setattr("pactown.sandbox_manager.subprocess.Popen", _fake_popen_factory(captured))

        manager.start_service(service=service, readme_path=readme_path, env={}, verbose=False)

        assert "cmd" in captured
        assert "electron" in captured["cmd"].lower()
