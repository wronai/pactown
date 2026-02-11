# Pactown – Multiplatform Testing Documentation

> **Version:** 0.1.153  
> **Last updated:** 2026-02-11  
> **Test runner:** pytest 7.4.4 / Python 3.13.7 / Linux 6.17.0

---

## Overview

Pactown supports building desktop, mobile, and web applications from markpact
files. The multiplatform test suite verifies that **every framework × every
target OS/platform** combination works correctly end-to-end:

1. **Scaffold** – config files are generated correctly
2. **Build commands** – correct CLI commands per framework and target
3. **Artifact collection** – correct glob patterns find built files
4. **Ansible deployment** – playbooks and inventories are generated with proper metadata

---

## Supported Platforms Matrix

### Desktop (6 frameworks × 3 OS = 18 combinations)

| Framework    | Language   | Linux              | Windows          | macOS            |
|-------------|------------|--------------------|--------------------|------------------|
| Electron    | JavaScript | `.AppImage`, `.snap`, `run.sh` | `.exe` (nsis)    | `.dmg`           |
| Tauri       | Rust       | `.AppImage`, `.deb` | `.msi`, `.exe`   | `.dmg`, `.app`   |
| PyInstaller | Python     | binary             | `.exe`            | binary           |
| PyQt        | Python     | binary             | `.exe`            | binary           |
| Tkinter     | Python     | binary             | `.exe`            | binary           |
| Flutter     | Dart       | binary + `.so`     | `.exe`            | `.app`           |

### Mobile (4 frameworks × 2 platforms = 8 combinations)

| Framework    | Language   | Android            | iOS              |
|-------------|------------|--------------------|--------------------|
| Capacitor   | JavaScript | `.apk`             | `.ipa`           |
| React Native| JavaScript | `.apk`             | `.ipa`           |
| Flutter     | Dart       | `.apk`             | `.ipa`           |
| Kivy        | Python     | `.apk`, `.aab`     | `.apk`           |

### Web (6 frameworks)

| Framework | Language   | Artifacts |
|-----------|-----------|-----------|
| FastAPI   | Python     | server (no build artifacts) |
| Flask     | Python     | server |
| Express   | JavaScript | server |
| Next.js   | JavaScript | server |
| React     | JavaScript | server |
| Vue       | JavaScript | server |

**Total: 32 framework×platform combinations tested.**

---

## Test Files

| File | Tests | Description |
|------|------:|-------------|
| `tests/test_cross_platform.py` | 230 | Full cross-platform matrix |
| `tests/test_ansible.py` | 192 | Ansible backend + artifact distribution |
| `tests/test_builders.py` | 185 | Builder unit tests + registry |
| **Total (multiplatform)** | **607** | |

---

## Test Classes Breakdown

### Desktop Framework Tests

| Class | Tests | What it verifies |
|-------|------:|------------------|
| `TestDesktopElectronAllOS` | 15 | `package.json` build targets (AppImage/nsis/dmg), `main.js` no-sandbox patch, devDependencies, appId, window size, artifacts × 3 OS, build commands, launcher scripts, all-OS combined |
| `TestDesktopTauriAllOS` | 8 | `tauri.conf.json` (bundle, identifier, window), artifacts × 3 OS, build command, all-OS combined |
| `TestDesktopPyInstallerAllOS` | 9 | `.spec` file generation, icon config, artifacts × 3 OS, build commands |
| `TestDesktopPyQtAllOS` | 7 | `.spec` file, artifacts × 3 OS, build commands |
| `TestDesktopTkinterAllOS` | 7 | `.spec` file, artifacts × 3 OS, build commands |
| `TestDesktopFlutterAllOS` | 7 | Scaffold noop, artifacts × 3 OS, `flutter build <os>` commands |

### Mobile Framework Tests

| Class | Tests | What it verifies |
|-------|------:|------------------|
| `TestMobileCapacitorAllPlatforms` | 15 | `capacitor.config.json`, `package.json` deps/scripts, platform deps (android/ios), webDir detection (dist/root/build), artifacts × 2 platforms, build commands, dual-platform |
| `TestMobileReactNativeAllPlatforms` | 8 | `app.json` (name, displayName), artifacts × 2, build commands (android/ios), dual-platform |
| `TestMobileFlutterAllPlatforms` | 5 | Scaffold noop, artifacts × 2, `flutter build apk/ios` |
| `TestMobileKivyAllPlatforms` | 10 | `buildozer.spec` (title, appId, fullscreen, icon, requirements), artifacts × 2, `buildozer <platform> debug`, APK+AAB |

### Web Framework Tests

| Class | Tests | What it verifies |
|-------|------:|------------------|
| `TestWebAllFrameworks` | 19 | Scaffold noop × 6 fw, build success × 6, build with cmd × 6, platform_name |

### Ansible Deployment Tests

| Class | Tests | What it verifies |
|-------|------:|------------------|
| `TestAnsibleDeployDesktopAllCombinations` | 18 | 6 frameworks × 3 OS: scaffold → artifacts → Ansible deploy → verify playbook + inventory |
| `TestAnsibleDeployMobileAllCombinations` | 8 | 4 frameworks × 2 platforms: scaffold → artifacts → Ansible deploy → verify |
| `TestAnsibleDeployWebAllFrameworks` | 6 | 6 web frameworks: build → Ansible deploy → verify |

### Cross-Cutting Tests

| Class | Tests | What it verifies |
|-------|------:|------------------|
| `TestFrameworkRegistryCompleteness` | 7 | All enums match registry, all have build_cmd + artifact_patterns |
| `TestBuildCommandMatrix` | 23 | Every framework × every target → correct CLI command |
| `TestArtifactCollectionMatrix` | 25 | Every framework × every OS → correct glob patterns, fallback for unknown, empty sandbox |
| `TestElectronNoSandboxAllPatterns` | 9 | CommonJS (single/double quotes), ES module (single/double), whenReady, app.on, prepend fallback, skip already patched, no main.js |
| `TestElectronBuilderFlagFilteringAllOS` | 13 | Linux/macOS/Windows host × targets, wine detection, empty/none defaults, dedup, cmd filtering |
| `TestElectronParallelBuild` | 2 | Single-target fallback, non-Electron fallback |

### End-to-End Tests

| Class | Tests | What it verifies |
|-------|------:|------------------|
| `TestFullE2EAllDesktopCombinations` | 5 | 5 frameworks × 3 OS each: scaffold → artifacts → collect → Ansible deploy |
| `TestFullE2EAllMobileCombinations` | 4 | 4 frameworks × 2 platforms each: scaffold → artifacts → collect → Ansible deploy |

---

## Running Tests

### All multiplatform tests

```bash
pytest tests/test_cross_platform.py tests/test_ansible.py tests/test_builders.py -v
```

### Only cross-platform matrix

```bash
pytest tests/test_cross_platform.py -v
```

### Specific framework

```bash
# All Electron tests
pytest tests/test_cross_platform.py -k "Electron" -v

# All Capacitor tests
pytest tests/test_cross_platform.py -k "Capacitor" -v

# All mobile tests
pytest tests/test_cross_platform.py -k "Mobile" -v

# All Ansible deployment tests
pytest tests/test_cross_platform.py -k "AnsibleDeploy" -v
```

### Specific OS/platform

```bash
# All Linux tests
pytest tests/test_cross_platform.py -k "linux" -v

# All iOS tests
pytest tests/test_cross_platform.py -k "ios" -v

# All Windows tests
pytest tests/test_cross_platform.py -k "windows" -v
```

### Full project suite

```bash
pytest tests/ -v
```

---

## Build Commands Reference

### Desktop

| Framework    | Target  | Command |
|-------------|---------|---------|
| Electron    | linux   | `npx electron-builder --linux` |
| Electron    | windows | `npx electron-builder --windows` (requires Wine on Linux) |
| Electron    | macos   | `npx electron-builder --mac` (requires macOS host) |
| Tauri       | all     | `npx tauri build` |
| PyInstaller | all     | `pyinstaller --onefile --windowed main.py` |
| PyQt        | all     | `pyinstaller --onefile --windowed main.py` |
| Tkinter     | all     | `pyinstaller --onefile --windowed main.py` |
| Flutter     | linux   | `flutter build linux` |
| Flutter     | windows | `flutter build windows` |
| Flutter     | macos   | `flutter build macos` |

### Mobile

| Framework    | Target  | Command |
|-------------|---------|---------|
| Capacitor   | android | `npx cap sync && npx cap build android` |
| Capacitor   | ios     | `npx cap sync && npx cap build ios` |
| React Native| android | `npx react-native build-android --mode=release` |
| React Native| ios     | `npx react-native build-ios --mode=release` |
| Flutter     | android | `flutter build apk --release` |
| Flutter     | ios     | `flutter build ios --release` |
| Kivy        | android | `buildozer android debug` |
| Kivy        | ios     | `buildozer ios debug` |

---

## Artifact Paths

### Desktop

| Framework    | OS      | Path pattern |
|-------------|---------|--------------|
| Electron    | linux   | `dist/*.AppImage`, `dist/*.snap`, `dist/run.sh`, `dist/README.txt` |
| Electron    | windows | `dist/*.exe` |
| Electron    | macos   | `dist/*.dmg` |
| Tauri       | all     | `src-tauri/target/release/bundle/**/*` |
| PyInstaller | linux   | `dist/app` (binary) |
| PyInstaller | windows | `dist/app.exe` |
| PyQt/Tkinter| same as PyInstaller | `dist/*` |
| Flutter     | linux   | `build/linux/**/*` |

### Mobile

| Framework    | Platform | Path pattern |
|-------------|----------|--------------|
| Capacitor   | android  | `android/app/build/outputs/apk/**/*.apk` |
| Capacitor   | ios      | `ios/App/build/**/*.ipa` |
| React Native| android  | `android/app/build/outputs/apk/**/*.apk` |
| React Native| ios      | `ios/build/**/*.ipa` |
| Flutter     | android  | `build/app/outputs/flutter-apk/*.apk` |
| Flutter     | ios      | `build/ios/**/*.ipa` |
| Kivy        | android  | `bin/*.apk`, `bin/*.aab` |

---

## Scaffold Config Files

| Framework    | Config file | Key fields |
|-------------|-------------|------------|
| Electron    | `package.json` | `build.linux.target`, `build.win.target`, `build.mac.target`, `build.appId`, `devDependencies` |
| Electron    | `main.js` | `app.commandLine.appendSwitch('no-sandbox')`, `BrowserWindow` width/height |
| Tauri       | `src-tauri/tauri.conf.json` | `tauri.bundle.active`, `tauri.bundle.identifier`, `tauri.bundle.targets`, `tauri.windows` |
| PyInstaller | `<app>.spec` | `Analysis`, `EXE`, `name`, `icon` |
| PyQt        | `<app>.spec` | same as PyInstaller |
| Tkinter     | `<app>.spec` | same as PyInstaller |
| Capacitor   | `capacitor.config.json` | `appId`, `appName`, `webDir`, `server.androidScheme` |
| Capacitor   | `package.json` | `@capacitor/core`, `@capacitor/cli`, `@capacitor/android`, `@capacitor/ios` (all `^6.0.0`) |
| React Native| `app.json` | `name`, `displayName` |
| Kivy        | `buildozer.spec` | `title`, `package.name`, `package.domain`, `requirements`, `fullscreen`, `icon.filename` |

---

## Electron-Specific: No-Sandbox Patch

AppImage on Linux requires `--no-sandbox` because the extracted binary cannot
have proper SUID ownership. The patch handles 4 code patterns:

| Pattern | Example | Injection point |
|---------|---------|-----------------|
| CommonJS require | `require('electron')` | After require line |
| ES module import | `from 'electron'` | After import line |
| app.whenReady fallback | `app.whenReady().then(...)` | Near the call |
| Ultimate fallback | any other code | Prepend at top of file |

Additionally, `run.sh` launcher and `README.txt` are generated for Linux builds.

---

## Electron Builder Cross-Compilation

| Host OS | `--linux` | `--windows` | `--mac` |
|---------|-----------|-------------|---------|
| Linux   | ✅        | ✅ (with Wine) | ❌     |
| macOS   | ✅        | ❌          | ✅      |
| Windows | ✅        | ✅          | ❌      |

The `_electron_builder_flags()` method automatically strips unsupported
cross-compilation flags and ensures at least one platform flag remains
(defaults to `--linux`).

---

## Sandbox Root Configuration

Artifacts are generated inside the configured sandbox root:

```
# .env (project root)
PACTOWN_SANDBOX_ROOT=.pactown
```

Structure after build:

```
.pactown/
├── my-electron-app/
│   ├── package.json
│   ├── main.js
│   └── dist/
│       ├── app-1.0.0.AppImage
│       ├── run.sh
│       └── README.txt
├── my-capacitor-app/
│   ├── capacitor.config.json
│   ├── package.json
│   └── android/app/build/outputs/apk/release/
│       └── app-release.apk
└── .cache/
    ├── npm/
    ├── venvs/
    ├── node_modules/
    └── electron-builder/
```

The `.pactown` directory is gitignored (`.pactown*/` in `.gitignore`).

---

## Test Report

### Run date: 2026-02-11 13:44 CET

### Environment

| Property | Value |
|----------|-------|
| Python   | 3.13.7 |
| OS       | Linux 6.17.0-12-generic |
| pytest   | 7.4.4 |
| pactown  | 0.1.153 |

### Results Summary

```
tests/test_cross_platform.py  230 passed    0.97s
tests/test_ansible.py         192 passed    1.55s
tests/test_builders.py        185 passed    0.88s
─────────────────────────────────────────────────
TOTAL                         607 passed    3.40s
```

### Full project suite

```
1146 passed, 2 skipped    9.53s
```

### Cross-Platform Matrix Results

#### Desktop: Scaffold ✅ | Artifacts ✅ | Build Cmd ✅ | Ansible ✅

```
                 linux    windows    macos
Electron          ✅        ✅        ✅
Tauri             ✅        ✅        ✅
PyInstaller       ✅        ✅        ✅
PyQt              ✅        ✅        ✅
Tkinter           ✅        ✅        ✅
Flutter           ✅        ✅        ✅
```

#### Mobile: Scaffold ✅ | Artifacts ✅ | Build Cmd ✅ | Ansible ✅

```
                 android    ios
Capacitor          ✅       ✅
React Native       ✅       ✅
Flutter            ✅       ✅
Kivy               ✅       ✅
```

#### Web: Scaffold ✅ | Build ✅ | Ansible ✅

```
FastAPI ✅  Flask ✅  Express ✅  Next ✅  React ✅  Vue ✅
```

#### Electron No-Sandbox Patch: All Patterns ✅

```
CommonJS require (single quotes)   ✅
CommonJS require (double quotes)   ✅
ES module import (single quotes)   ✅
ES module import (double quotes)   ✅
app.whenReady fallback             ✅
app.on fallback                    ✅
Ultimate fallback (prepend)        ✅
Skip already patched               ✅
No main.js                         ✅
```

#### Electron Builder Flag Filtering ✅

```
Linux host: keeps --linux           ✅
Linux host: strips --mac            ✅
Linux host: strips --windows        ✅
Linux host: keeps --windows (wine)  ✅
Linux host: multi-target            ✅
macOS host: keeps --mac             ✅
macOS host: keeps --linux           ✅
Windows host: keeps --windows       ✅
Windows host: strips --mac          ✅
Empty targets → --linux             ✅
None targets → --linux              ✅
No duplicates                       ✅
Filter cmd strips unsupported       ✅
```

#### Framework Registry Completeness ✅

```
All desktop frameworks registered   ✅
All mobile frameworks registered    ✅
All have default build command      ✅
All have artifact patterns          ✅
Desktop enums match registry        ✅
Mobile enums match registry         ✅
Web enums complete                  ✅
```

#### End-to-End (scaffold → artifacts → Ansible deploy) ✅

```
Desktop: 5 frameworks × 3 OS = 15 sub-tests   ✅
Mobile:  4 frameworks × 2 platforms = 8        ✅
```

### Detailed Test List (230 cross-platform tests)

```
TestDesktopElectronAllOS (15 tests)
  ✅ test_scaffold_creates_package_json_and_main_js
  ✅ test_scaffold_package_json_has_all_os_targets
  ✅ test_scaffold_main_js_has_no_sandbox
  ✅ test_scaffold_electron_dev_deps
  ✅ test_scaffold_app_id
  ✅ test_scaffold_custom_window_size
  ✅ test_artifacts_per_os[linux]
  ✅ test_artifacts_per_os[windows]
  ✅ test_artifacts_per_os[macos]
  ✅ test_build_cmd_per_os[linux]
  ✅ test_build_cmd_per_os[windows]
  ✅ test_build_cmd_per_os[macos]
  ✅ test_build_cmd_multi_os
  ✅ test_linux_artifacts_include_launcher
  ✅ test_all_os_artifacts_combined

TestDesktopTauriAllOS (8 tests)
  ✅ test_scaffold_creates_tauri_conf
  ✅ test_scaffold_custom_app_id
  ✅ test_scaffold_custom_window_size
  ✅ test_artifacts_per_os[linux]
  ✅ test_artifacts_per_os[windows]
  ✅ test_artifacts_per_os[macos]
  ✅ test_build_cmd
  ✅ test_all_os_artifacts_combined

TestDesktopPyInstallerAllOS (9 tests)
  ✅ test_scaffold_creates_spec
  ✅ test_scaffold_with_icon
  ✅ test_artifacts_per_os[linux]
  ✅ test_artifacts_per_os[windows]
  ✅ test_artifacts_per_os[macos]
  ✅ test_build_cmd_same_for_all_os[linux]
  ✅ test_build_cmd_same_for_all_os[windows]
  ✅ test_build_cmd_same_for_all_os[macos]
  ✅ test_all_os_artifacts_combined

TestDesktopPyQtAllOS (7 tests)
  ✅ test_scaffold_creates_spec
  ✅ test_artifacts_per_os[linux]
  ✅ test_artifacts_per_os[windows]
  ✅ test_artifacts_per_os[macos]
  ✅ test_build_cmd_same_for_all_os[linux]
  ✅ test_build_cmd_same_for_all_os[windows]
  ✅ test_build_cmd_same_for_all_os[macos]

TestDesktopTkinterAllOS (7 tests)
  ✅ test_scaffold_creates_spec
  ✅ test_artifacts_per_os[linux]
  ✅ test_artifacts_per_os[windows]
  ✅ test_artifacts_per_os[macos]
  ✅ test_build_cmd_same_for_all_os[linux]
  ✅ test_build_cmd_same_for_all_os[windows]
  ✅ test_build_cmd_same_for_all_os[macos]

TestDesktopFlutterAllOS (7 tests)
  ✅ test_scaffold_noop
  ✅ test_artifacts_per_os[linux]
  ✅ test_artifacts_per_os[windows]
  ✅ test_artifacts_per_os[macos]
  ✅ test_build_cmd_per_os[linux]
  ✅ test_build_cmd_per_os[windows]
  ✅ test_build_cmd_per_os[macos]

TestMobileCapacitorAllPlatforms (15 tests)
  ✅ test_scaffold_creates_config
  ✅ test_scaffold_config_content
  ✅ test_scaffold_custom_app_id
  ✅ test_scaffold_package_json_deps
  ✅ test_scaffold_android_platform_dep
  ✅ test_scaffold_ios_platform_dep
  ✅ test_scaffold_dual_platform_deps
  ✅ test_scaffold_scripts
  ✅ test_scaffold_web_dir_detection_dist
  ✅ test_scaffold_web_dir_detection_root
  ✅ test_artifacts_per_platform[android]
  ✅ test_artifacts_per_platform[ios]
  ✅ test_build_cmd_per_platform[android]
  ✅ test_build_cmd_per_platform[ios]
  ✅ test_dual_platform_artifacts

TestMobileReactNativeAllPlatforms (8 tests)
  ✅ test_scaffold_creates_app_json
  ✅ test_scaffold_app_json_content
  ✅ test_scaffold_custom_display_name
  ✅ test_artifacts_per_platform[android]
  ✅ test_artifacts_per_platform[ios]
  ✅ test_build_cmd_android
  ✅ test_build_cmd_ios
  ✅ test_dual_platform_artifacts

TestMobileFlutterAllPlatforms (5 tests)
  ✅ test_scaffold_noop
  ✅ test_artifacts_per_platform[android]
  ✅ test_artifacts_per_platform[ios]
  ✅ test_build_cmd_android
  ✅ test_build_cmd_ios

TestMobileKivyAllPlatforms (10 tests)
  ✅ test_scaffold_creates_buildozer_spec
  ✅ test_scaffold_custom_app_id
  ✅ test_scaffold_fullscreen
  ✅ test_scaffold_no_fullscreen
  ✅ test_scaffold_icon
  ✅ test_artifacts_per_platform[android]
  ✅ test_artifacts_per_platform[ios]
  ✅ test_build_cmd_android
  ✅ test_build_cmd_ios
  ✅ test_android_apk_and_aab

TestWebAllFrameworks (19 tests)
  ✅ test_scaffold_noop[fastapi]
  ✅ test_scaffold_noop[flask]
  ✅ test_scaffold_noop[express]
  ✅ test_scaffold_noop[next]
  ✅ test_scaffold_noop[react]
  ✅ test_scaffold_noop[vue]
  ✅ test_build_no_cmd_returns_success[fastapi]
  ✅ test_build_no_cmd_returns_success[flask]
  ✅ test_build_no_cmd_returns_success[express]
  ✅ test_build_no_cmd_returns_success[next]
  ✅ test_build_no_cmd_returns_success[react]
  ✅ test_build_no_cmd_returns_success[vue]
  ✅ test_build_with_cmd_runs_shell × 6 frameworks
  ✅ test_platform_name

TestAnsibleDeployDesktopAllCombinations (18 tests)
  ✅ electron-linux, electron-windows, electron-macos
  ✅ tauri-linux, tauri-windows, tauri-macos
  ✅ pyinstaller-linux, pyinstaller-windows, pyinstaller-macos
  ✅ pyqt-linux, pyqt-windows, pyqt-macos
  ✅ tkinter-linux, tkinter-windows, tkinter-macos
  ✅ flutter-linux, flutter-windows, flutter-macos

TestAnsibleDeployMobileAllCombinations (8 tests)
  ✅ capacitor-android, capacitor-ios
  ✅ react-native-android, react-native-ios
  ✅ flutter-android, flutter-ios
  ✅ kivy-android, kivy-ios

TestAnsibleDeployWebAllFrameworks (6 tests)
  ✅ fastapi, flask, express, next, react, vue

TestFrameworkRegistryCompleteness (7 tests)
  ✅ all_desktop_frameworks_registered
  ✅ all_mobile_frameworks_registered
  ✅ all_frameworks_have_build_cmd
  ✅ all_frameworks_have_artifact_patterns
  ✅ desktop_enums_match_registry
  ✅ mobile_enums_match_registry
  ✅ web_enums

TestBuildCommandMatrix (23 tests)
  ✅ electron × 6 target combinations
  ✅ tauri (ignores targets)
  ✅ pyinstaller, tkinter, pyqt × 3 OS each
  ✅ flutter desktop × 3 OS
  ✅ capacitor, react-native, flutter-mobile, kivy × 2 platforms each
  ✅ unknown desktop/mobile → empty

TestArtifactCollectionMatrix (25 tests)
  ✅ electron, tauri, pyinstaller, pyqt, tkinter × linux, windows, macos
  ✅ flutter desktop linux
  ✅ capacitor, react-native, kivy × android, ios
  ✅ flutter mobile android
  ✅ unknown desktop/mobile fallback
  ✅ empty sandbox → no artifacts

TestElectronNoSandboxAllPatterns (9 tests)
  ✅ All 4 injection patterns + skip + no-file

TestElectronBuilderFlagFilteringAllOS (13 tests)
  ✅ Linux/macOS/Windows host × targets, wine, defaults, dedup

TestElectronParallelBuild (2 tests)
  ✅ Single-target and non-Electron fallback

TestFullE2EAllDesktopCombinations (5 tests → 15 sub-tests)
  ✅ electron, tauri, pyinstaller, pyqt, tkinter × linux, windows, macos

TestFullE2EAllMobileCombinations (4 tests → 8 sub-tests)
  ✅ capacitor, react-native, flutter, kivy × android, ios
```

---

## Adding a New Framework

1. Add enum value to `DesktopFramework` / `MobileFramework` in `src/pactown/targets.py`
2. Add `FrameworkMeta` entry to `FRAMEWORK_REGISTRY`
3. Add scaffold method in `src/pactown/builders/desktop.py` or `mobile.py`
4. Add artifact patterns to `_collect_artifacts()`
5. Add build command to `_default_build_cmd()`
6. Add test entries to `_DESKTOP_ARTIFACTS` / `_MOBILE_ARTIFACTS` in `test_cross_platform.py`
7. Add parametrize entries to `TestAnsibleDeployDesktop/MobileAllCombinations`
8. Run `pytest tests/test_cross_platform.py -v` to verify
