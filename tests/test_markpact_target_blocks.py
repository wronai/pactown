"""Tests for markpact:target and markpact:build block parsing."""

from pactown.markpact_blocks import parse_blocks, extract_target_config, extract_build_cmd
from pactown.targets import TargetPlatform


def test_parse_target_block_yaml() -> None:
    md = """\
# My Desktop App

```yaml markpact:target
platform: desktop
framework: electron
app_name: MyApp
window_width: 1024
window_height: 768
```

```javascript markpact:file path=index.html
<h1>Hello</h1>
```
"""
    blocks = parse_blocks(md)

    target_blocks = [b for b in blocks if b.kind == "target"]
    assert len(target_blocks) == 1
    assert target_blocks[0].lang == "yaml"
    assert "desktop" in target_blocks[0].body

    file_blocks = [b for b in blocks if b.kind == "file"]
    assert len(file_blocks) == 1


def test_extract_target_config_desktop() -> None:
    md = """\
```yaml markpact:target
platform: desktop
framework: tauri
targets:
  - linux
  - windows
```

```bash markpact:run
npx tauri dev
```
"""
    blocks = parse_blocks(md)
    cfg = extract_target_config(blocks)

    assert cfg is not None
    assert cfg.platform == TargetPlatform.DESKTOP
    assert cfg.framework == "tauri"
    assert cfg.targets == ["linux", "windows"]


def test_extract_target_config_mobile() -> None:
    md = """\
```yaml markpact:target
platform: mobile
framework: capacitor
app_id: com.example.myapp
targets:
  - android
  - ios
```
"""
    blocks = parse_blocks(md)
    cfg = extract_target_config(blocks)

    assert cfg is not None
    assert cfg.platform == TargetPlatform.MOBILE
    assert cfg.framework == "capacitor"
    assert cfg.app_id == "com.example.myapp"


def test_extract_target_config_none_when_missing() -> None:
    md = """\
```python markpact:file path=main.py
print("hello")
```
"""
    blocks = parse_blocks(md)
    cfg = extract_target_config(blocks)
    assert cfg is None


def test_parse_build_block() -> None:
    md = """\
```bash markpact:build
npx electron-builder --linux --windows
```
"""
    blocks = parse_blocks(md)

    build_blocks = [b for b in blocks if b.kind == "build"]
    assert len(build_blocks) == 1
    assert build_blocks[0].body == "npx electron-builder --linux --windows"


def test_extract_build_cmd() -> None:
    md = """\
```bash markpact:build
pyinstaller --onefile main.py
```

```bash markpact:run
python main.py
```
"""
    blocks = parse_blocks(md)
    cmd = extract_build_cmd(blocks)
    assert cmd == "pyinstaller --onefile main.py"


def test_extract_build_cmd_none_when_missing() -> None:
    md = """\
```bash markpact:run
python main.py
```
"""
    blocks = parse_blocks(md)
    cmd = extract_build_cmd(blocks)
    assert cmd is None


def test_full_desktop_markpact() -> None:
    """Full integration test: parse a complete desktop markpact file."""
    md = """\
# Calculator App

A simple calculator built with Electron.

```yaml markpact:target
platform: desktop
framework: electron
app_name: Calculator
window_width: 400
window_height: 600
```

```javascript markpact:file path=index.html
<html>
<body>
<h1>Calculator</h1>
</body>
</html>
```

```javascript markpact:deps
electron
```

```bash markpact:build
npx electron-builder --linux
```

```bash markpact:run
npx electron .
```
"""
    blocks = parse_blocks(md)

    assert len(blocks) == 5

    target_cfg = extract_target_config(blocks)
    assert target_cfg is not None
    assert target_cfg.platform == TargetPlatform.DESKTOP
    assert target_cfg.framework == "electron"
    assert target_cfg.app_name == "Calculator"
    assert target_cfg.window_width == 400
    assert target_cfg.window_height == 600

    build_cmd = extract_build_cmd(blocks)
    assert build_cmd == "npx electron-builder --linux"

    file_blocks = [b for b in blocks if b.kind == "file"]
    assert len(file_blocks) == 1
    assert file_blocks[0].get_path() == "index.html"

    deps_blocks = [b for b in blocks if b.kind == "deps"]
    assert len(deps_blocks) == 1
    assert "electron" in deps_blocks[0].body

    run_blocks = [b for b in blocks if b.kind == "run"]
    assert len(run_blocks) == 1


def test_full_mobile_markpact() -> None:
    """Full integration test: parse a complete mobile markpact file."""
    md = """\
# Todo App

A mobile todo list.

```yaml markpact:target
platform: mobile
framework: kivy
app_id: com.example.todo
targets:
  - android
```

```python markpact:file path=main.py
from kivy.app import App
class TodoApp(App):
    pass
```

```python markpact:deps
kivy
buildozer
```

```bash markpact:build
buildozer android debug
```
"""
    blocks = parse_blocks(md)

    target_cfg = extract_target_config(blocks)
    assert target_cfg is not None
    assert target_cfg.platform == TargetPlatform.MOBILE
    assert target_cfg.framework == "kivy"
    assert target_cfg.targets == ["android"]

    build_cmd = extract_build_cmd(blocks)
    assert build_cmd == "buildozer android debug"


def test_get_meta_value() -> None:
    md = """\
```python markpact:file path=main.py format=utf8
print("hi")
```
"""
    blocks = parse_blocks(md)
    assert len(blocks) == 1
    assert blocks[0].get_meta_value("path") == "main.py"
    assert blocks[0].get_meta_value("format") == "utf8"
    assert blocks[0].get_meta_value("missing") is None
