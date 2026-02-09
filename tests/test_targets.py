"""Tests for pactown.targets module."""

from pactown.targets import (
    TargetPlatform,
    TargetConfig,
    DesktopFramework,
    MobileFramework,
    FrameworkMeta,
    get_framework_meta,
    list_frameworks,
    infer_target_from_deps,
    FRAMEWORK_REGISTRY,
)


# ---------------------------------------------------------------------------
# TargetPlatform
# ---------------------------------------------------------------------------

def test_target_platform_values() -> None:
    assert TargetPlatform.WEB.value == "web"
    assert TargetPlatform.DESKTOP.value == "desktop"
    assert TargetPlatform.MOBILE.value == "mobile"


# ---------------------------------------------------------------------------
# TargetConfig.from_yaml_body
# ---------------------------------------------------------------------------

def test_target_config_from_yaml_desktop() -> None:
    body = """\
platform: desktop
framework: electron
app_name: MyApp
window_width: 1280
window_height: 720
"""
    cfg = TargetConfig.from_yaml_body(body)
    assert cfg.platform == TargetPlatform.DESKTOP
    assert cfg.framework == "electron"
    assert cfg.app_name == "MyApp"
    assert cfg.window_width == 1280
    assert cfg.window_height == 720
    assert cfg.is_desktop
    assert cfg.is_buildable
    assert not cfg.needs_port


def test_target_config_from_yaml_mobile() -> None:
    body = """\
platform: mobile
framework: capacitor
targets:
  - android
  - ios
app_id: com.example.myapp
"""
    cfg = TargetConfig.from_yaml_body(body)
    assert cfg.platform == TargetPlatform.MOBILE
    assert cfg.framework == "capacitor"
    assert cfg.targets == ["android", "ios"]
    assert cfg.app_id == "com.example.myapp"
    assert cfg.is_mobile
    assert cfg.is_buildable
    assert not cfg.needs_port


def test_target_config_defaults_to_web() -> None:
    cfg = TargetConfig.from_yaml_body("")
    assert cfg.platform == TargetPlatform.WEB
    assert cfg.is_web
    assert cfg.needs_port
    assert not cfg.is_buildable


def test_target_config_from_dict_targets_as_string() -> None:
    cfg = TargetConfig.from_dict({"platform": "desktop", "targets": "linux, windows"})
    assert cfg.targets == ["linux", "windows"]


def test_target_config_effective_build_targets_desktop() -> None:
    cfg = TargetConfig.from_dict({"platform": "desktop"})
    assert cfg.effective_build_targets() == ["linux"]


def test_target_config_effective_build_targets_mobile() -> None:
    cfg = TargetConfig.from_dict({"platform": "mobile"})
    assert cfg.effective_build_targets() == ["android"]


def test_target_config_effective_build_targets_explicit() -> None:
    cfg = TargetConfig.from_dict({"platform": "mobile", "targets": ["ios"]})
    assert cfg.effective_build_targets() == ["ios"]


def test_target_config_extra_keys_preserved() -> None:
    cfg = TargetConfig.from_dict({"platform": "desktop", "custom_key": "val"})
    assert cfg.extra == {"custom_key": "val"}


# ---------------------------------------------------------------------------
# Framework registry
# ---------------------------------------------------------------------------

def test_get_framework_meta_electron() -> None:
    meta = get_framework_meta("electron")
    assert meta is not None
    assert meta.platform == TargetPlatform.DESKTOP
    assert meta.needs_node


def test_get_framework_meta_capacitor() -> None:
    meta = get_framework_meta("capacitor")
    assert meta is not None
    assert meta.platform == TargetPlatform.MOBILE
    assert meta.needs_node


def test_get_framework_meta_pyinstaller() -> None:
    meta = get_framework_meta("pyinstaller")
    assert meta is not None
    assert meta.platform == TargetPlatform.DESKTOP
    assert meta.needs_python


def test_get_framework_meta_unknown() -> None:
    assert get_framework_meta("nonexistent") is None


def test_list_frameworks_all() -> None:
    all_fw = list_frameworks()
    assert len(all_fw) == len(FRAMEWORK_REGISTRY)


def test_list_frameworks_desktop_only() -> None:
    desktop = list_frameworks(TargetPlatform.DESKTOP)
    assert all(f.platform == TargetPlatform.DESKTOP for f in desktop)
    assert len(desktop) > 0


def test_list_frameworks_mobile_only() -> None:
    mobile = list_frameworks(TargetPlatform.MOBILE)
    assert all(f.platform == TargetPlatform.MOBILE for f in mobile)
    assert len(mobile) > 0


# ---------------------------------------------------------------------------
# infer_target_from_deps
# ---------------------------------------------------------------------------

def test_infer_desktop_from_electron_dep() -> None:
    assert infer_target_from_deps(["electron"]) == TargetPlatform.DESKTOP


def test_infer_mobile_from_capacitor_dep() -> None:
    assert infer_target_from_deps(["@capacitor/core"]) == TargetPlatform.MOBILE


def test_infer_web_from_fastapi_dep() -> None:
    assert infer_target_from_deps(["fastapi"]) == TargetPlatform.WEB


def test_infer_web_from_empty_deps() -> None:
    assert infer_target_from_deps([]) == TargetPlatform.WEB


def test_infer_mobile_over_desktop_when_both() -> None:
    # mobile hints take priority
    assert infer_target_from_deps(["react-native", "electron"]) == TargetPlatform.MOBILE
