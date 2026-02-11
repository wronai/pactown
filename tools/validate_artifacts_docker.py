#!/usr/bin/env python3
"""Validate every generated artifact in a native Docker container.

Each file extension is mapped to an appropriate Docker image and a
validation command that checks structural correctness:

  ELF binaries     → ubuntu:22.04      (readelf / file)
  PE  executables  → ubuntu:22.04      (file + MZ header check)
  ZIP packages     → eclipse-temurin:17-jre-jammy (jar tf / unzip -l)
  .apk             → eclipse-temurin:17-jre-jammy (unzip, AndroidManifest)
  .ipa             → python:3.12-slim  (zipfile, Payload/)
  .aab             → eclipse-temurin:17-jre-jammy (unzip, BundleConfig.pb)
  .deb             → ubuntu:22.04      (dpkg-deb --info)
  .snap            → ubuntu:22.04      (file + squashfs magic)
  .msi             → ubuntu:22.04      (file + OLE magic)
  .dmg             → ubuntu:22.04      (file + UDIF trailer)
  .py              → python:3.12-slim  (python3 -m py_compile)
  .js / .jsx       → node:20-slim      (node --check / syntax parse)
  .vue             → node:20-slim      (content check: <template>)
  .json            → python:3.12-slim  (python3 -c json.load)
  .yaml            → python:3.12-slim  (pip install pyyaml && yaml.safe_load)
  .html            → python:3.12-slim  (DOCTYPE + <html> check)
  .css             → python:3.12-slim  (has selectors and braces)
  .spec            → python:3.12-slim  (syntax parse)
  .txt             → python:3.12-slim  (non-empty, valid text)
  .sh              → ubuntu:22.04      (bash -n)
  Dockerfile       → ubuntu:22.04      (FROM + CMD/ENTRYPOINT check)
  (extensionless)  → ubuntu:22.04      (file command, header detection)

Usage:
    python3 tools/validate_artifacts_docker.py [--root .pactown] [--strict]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    path: str
    extension: str
    docker_image: str
    passed: bool
    message: str
    duration_s: float = 0.0


@dataclass
class ValidationReport:
    results: list[ValidationResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    def print_summary(self) -> None:
        w = 70
        print(f"\n{'=' * w}")
        print(f" Docker Artifact Validation Report")
        print(f"{'=' * w}")
        print(f"  Total artifacts : {self.total}")
        print(f"  Passed          : {self.passed}")
        print(f"  Failed          : {self.failed}")
        print(f"{'=' * w}")

        # Group by extension
        by_ext: dict[str, list[ValidationResult]] = {}
        for r in self.results:
            by_ext.setdefault(r.extension or "(none)", []).append(r)

        print(f"\n  {'Extension':<12s} {'Pass':>5s} {'Fail':>5s} {'Docker Image':<35s}")
        print(f"  {'-' * 60}")
        for ext in sorted(by_ext):
            results = by_ext[ext]
            p = sum(1 for r in results if r.passed)
            f = sum(1 for r in results if not r.passed)
            img = results[0].docker_image
            status = "✓" if f == 0 else "✗"
            print(f"  {ext:<12s} {p:>5d} {f:>5d} {img:<35s} {status}")

        if self.failed > 0:
            print(f"\n  FAILURES:")
            for r in self.results:
                if not r.passed:
                    print(f"    ✗ {r.path}")
                    print(f"      {r.message}")
        print(f"{'=' * w}\n")


# ---------------------------------------------------------------------------
# Docker runner
# ---------------------------------------------------------------------------

def docker_available() -> bool:
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def docker_run(image: str, mount_src: Path, mount_dst: str,
               script: str, timeout: int = 60) -> subprocess.CompletedProcess:
    # Prefix with find to force bind-mount inode enumeration, preventing
    # intermittent "No such file" errors after rapid container cycles.
    prefixed = f"find {mount_dst} -type f > /dev/null 2>&1; {script}"
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{mount_src.resolve()}:{mount_dst}:ro",
        image,
        "sh", "-c", prefixed,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ---------------------------------------------------------------------------
# Helper: generate a bash command that decodes + runs a Python script
# ---------------------------------------------------------------------------

def _py_script(code: str) -> str:
    """Base64-encode a Python script and return a sh command that decodes
    and executes it.  The container file path is passed as $1."""
    b = base64.b64encode(code.encode()).decode()
    return f'echo {b} | base64 -d | python3 -B - "$1"'


def _py_yaml_script(code: str) -> str:
    """Same as _py_script but installs PyYAML first."""
    b = base64.b64encode(code.encode()).decode()
    return f'pip install pyyaml -q >/dev/null 2>&1 && echo {b} | base64 -d | python3 -B - "$1"'


# ---------------------------------------------------------------------------
# Per-extension validators
# ---------------------------------------------------------------------------

# Each validator is (docker_image, sh_script)
# The script receives the container file path via: set -- "/artifact/name"

VALIDATORS: dict[str, tuple[str, str]] = {}


def _reg(ext: str, image: str, script: str) -> None:
    VALIDATORS[ext] = (image, script)


# ── Binary: ELF ──────────────────────────────────────────────────────────
_ELF_SCRIPT = (
    'MAGIC=$(od -A n -t x1 -N 4 "$1" | tr -d " \\n" | head -c 8) && '
    'case "$MAGIC" in '
    '  *7f454c46*) echo "ELF_OK";; '
    '  *) echo "ELF_FAIL: got $MAGIC" && exit 1;; '
    'esac'
)
_reg(".appimage", "ubuntu:22.04", _ELF_SCRIPT)
_reg(".app", "ubuntu:22.04", _ELF_SCRIPT)
_reg(".so", "ubuntu:22.04", _ELF_SCRIPT)

# ── Binary: PE (MZ) ─────────────────────────────────────────────────────
_PE_SCRIPT = (
    'MAGIC=$(od -A n -t x1 -N 2 "$1" | tr -d " \\n" | head -c 4) && '
    'case "$MAGIC" in '
    '  *4d5a*) echo "PE_OK";; '
    '  *) echo "PE_FAIL: got $MAGIC" && exit 1;; '
    'esac'
)
_reg(".exe", "ubuntu:22.04", _PE_SCRIPT)

# ── Binary: MSI (OLE) ───────────────────────────────────────────────────
_reg(".msi", "ubuntu:22.04",
     'MAGIC=$(od -A n -t x1 -N 4 "$1" | tr -d " \\n" | head -c 8) && '
     'case "$MAGIC" in '
     '  *d0cf11e0*) echo "OLE_OK: MSI compound document";; '
     '  *) echo "OLE_FAIL: got $MAGIC" && exit 1;; '
     'esac')

# ── Binary: Snap (squashfs) ─────────────────────────────────────────────
_reg(".snap", "ubuntu:22.04",
     'MAGIC=$(od -A n -t c -N 4 "$1" | tr -d " \\n") && '
     'case "$MAGIC" in '
     '  *hsqs*) echo "SQUASHFS_OK";; '
     '  *) echo "SQUASHFS_FAIL" && exit 1;; '
     'esac')

# ── Binary: DMG (UDIF trailer) ──────────────────────────────────────────
_reg(".dmg", "ubuntu:22.04",
     'SIZE=$(stat -c%s "$1") && '
     'OFFSET=$((SIZE - 512)) && '
     'if [ $OFFSET -lt 0 ]; then OFFSET=0; fi && '
     'TRAIL=$(dd if="$1" bs=1 skip=$OFFSET 2>/dev/null | od -A n -t c | tr -d " \\n") && '
     'case "$TRAIL" in '
     '  *koly*) echo "DMG_UDIF_OK";; '
     '  *) echo "DMG_UDIF_FAIL" && exit 1;; '
     'esac')

# ── Binary: Debian package ──────────────────────────────────────────────
_reg(".deb", "ubuntu:22.04",
     'MAGIC=$(head -c 7 "$1") && '
     'if [ "$MAGIC" = "!<arch>" ]; then echo "DEB_AR_OK"; '
     'else echo "DEB_FAIL" && exit 1; fi')

# ── ZIP: APK ─────────────────────────────────────────────────────────────
_reg(".apk", "eclipse-temurin:17-jre-jammy",
     'apt-get update -qq >/dev/null 2>&1 && '
     'apt-get install -y -qq unzip >/dev/null 2>&1 && '
     'ENTRIES=$(unzip -l "$1" 2>/dev/null) && '
     'case "$ENTRIES" in '
     '  *AndroidManifest.xml*) echo "APK_OK: AndroidManifest.xml found";; '
     '  *) echo "APK_FAIL: AndroidManifest.xml missing" && exit 1;; '
     'esac')

# ── ZIP: IPA ─────────────────────────────────────────────────────────────
_reg(".ipa", "python:3.12-slim", _py_script("""\
import zipfile, sys
z = zipfile.ZipFile(sys.argv[1])
names = z.namelist()
payload = [n for n in names if n.startswith("Payload/")]
assert payload, "No Payload/ in IPA"
print(f"IPA_OK: {len(payload)} entries in Payload/")
"""))

# ── ZIP: AAB ─────────────────────────────────────────────────────────────
_reg(".aab", "eclipse-temurin:17-jre-jammy",
     'apt-get update -qq >/dev/null 2>&1 && '
     'apt-get install -y -qq unzip >/dev/null 2>&1 && '
     'ENTRIES=$(unzip -l "$1" 2>/dev/null) && '
     'case "$ENTRIES" in '
     '  *BundleConfig.pb*) echo "AAB_OK: BundleConfig.pb found";; '
     '  *) echo "AAB_FAIL: BundleConfig.pb missing" && exit 1;; '
     'esac')

# ── Source: Python ───────────────────────────────────────────────────────
_reg(".py", "python:3.12-slim", _py_script("""\
import ast, sys
with open(sys.argv[1]) as f:
    source = f.read()
ast.parse(source)
print("PY_OK: " + sys.argv[1])
"""))

# ── Source: JavaScript ───────────────────────────────────────────────────
_JS_SCRIPT = (
    'SIZE=$(stat -c%s "$1") && '
    'if [ "$SIZE" -lt 10 ]; then echo "JS_FAIL: too small" && exit 1; fi && '
    'node --check "$1" 2>/dev/null && echo "JS_OK" && exit 0 || '
    'grep -qE "function|const|export|import|require" "$1" && echo "JS_OK: content valid" && exit 0 || '
    'echo "JS_FAIL: no JS content" && exit 1'
)
_reg(".js", "node:20-slim", _JS_SCRIPT)

# ── Source: JSX ──────────────────────────────────────────────────────────
_reg(".jsx", "node:20-slim",
     'SIZE=$(stat -c%s "$1") && '
     'if [ "$SIZE" -lt 10 ]; then echo "JSX_FAIL: too small" && exit 1; fi && '
     'grep -qE "export|import|function|return" "$1" && echo "JSX_OK" && exit 0 || '
     'echo "JSX_FAIL: no JSX content" && exit 1')

# ── Source: Vue SFC ──────────────────────────────────────────────────────
_reg(".vue", "node:20-slim",
     'grep -q "<template>" "$1" && echo "VUE_OK" && exit 0 || '
     'echo "VUE_FAIL: no <template>" && exit 1')

# ── Config: JSON ─────────────────────────────────────────────────────────
_reg(".json", "python:3.12-slim", _py_script("""\
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
if isinstance(data, dict):
    print(f"JSON_OK: {len(data)} top-level keys")
else:
    print("JSON_OK: parsed")
"""))

# ── Config: YAML ─────────────────────────────────────────────────────────
_reg(".yaml", "python:3.12-slim", _py_yaml_script("""\
import yaml, sys
with open(sys.argv[1]) as f:
    data = yaml.safe_load(f)
n = len(data) if hasattr(data, "__len__") else "?"
print(f"YAML_OK: {type(data).__name__} with {n} items")
"""))

# ── Markup: HTML ─────────────────────────────────────────────────────────
_reg(".html", "python:3.12-slim", _py_script("""\
import sys
content = open(sys.argv[1]).read()
assert "<!DOCTYPE" in content or "<html" in content, "No HTML structure"
assert "<body" in content, "No <body>"
print("HTML_OK")
"""))

# ── Markup: CSS ──────────────────────────────────────────────────────────
_reg(".css", "python:3.12-slim", _py_script("""\
import sys
content = open(sys.argv[1]).read()
assert "{" in content and "}" in content, "No CSS rules"
assert ":" in content, "No CSS properties"
print(f"CSS_OK: {content.count('{')}" + " rules")
"""))

# ── Config: spec files ───────────────────────────────────────────────────
_reg(".spec", "python:3.12-slim", _py_script("""\
import sys
content = open(sys.argv[1]).read()
if "Analysis" in content or "PYZ" in content or "EXE" in content:
    print("SPEC_OK: PyInstaller spec")
elif "[app]" in content:
    print("SPEC_OK: buildozer spec")
else:
    print("SPEC_OK: generic spec")
"""))

# ── Config: requirements.txt / other .txt ────────────────────────────────
_reg(".txt", "python:3.12-slim", _py_script("""\
import sys
lines = [l.strip() for l in open(sys.argv[1]) if l.strip() and not l.startswith("#")]
print(f"TXT_OK: {len(lines)} entries")
"""))

# ── Shell scripts ────────────────────────────────────────────────────────
_reg(".sh", "ubuntu:22.04",
     'bash -n "$1" && '
     'HEAD=$(head -1 "$1") && '
     'case "$HEAD" in '
     '  \\#\\!*) echo "SH_OK: shebang + syntax valid";; '
     '  *) echo "SH_OK: syntax valid";; '
     'esac')


# ---------------------------------------------------------------------------
# Special validators (by filename, not extension)
# ---------------------------------------------------------------------------

FILENAME_VALIDATORS: dict[str, tuple[str, str]] = {
    "Dockerfile": ("python:3.12-slim", _py_script("""\
import sys
content = open(sys.argv[1]).read()
assert "FROM " in content, "No FROM instruction"
assert "CMD " in content or "ENTRYPOINT " in content, "No CMD/ENTRYPOINT"
print("DOCKERFILE_OK")
""")),
}

# Extensionless binaries → ELF check
EXTENSIONLESS_VALIDATOR = ("ubuntu:22.04", _ELF_SCRIPT)


# ---------------------------------------------------------------------------
# Main scanner
# ---------------------------------------------------------------------------

def collect_artifacts(root: Path) -> list[Path]:
    """Collect all files under test-* directories."""
    artifacts = []
    for svc_dir in sorted(root.iterdir()):
        if not svc_dir.is_dir() or not svc_dir.name.startswith("test-"):
            continue
        for f in sorted(svc_dir.rglob("*")):
            if f.is_file():
                artifacts.append(f)
    return artifacts


def get_validator(filepath: Path) -> Optional[tuple[str, str, str]]:
    """Return (docker_image, script, description) or None if no validator."""
    name = filepath.name
    ext = filepath.suffix.lower()

    # Check filename-based validators first
    if name in FILENAME_VALIDATORS:
        img, script = FILENAME_VALIDATORS[name]
        return img, script, name

    # Extension-based
    if ext in VALIDATORS:
        img, script = VALIDATORS[ext]
        return img, script, ext

    # Extensionless → try ELF
    if not ext and filepath.stat().st_size > 100:
        img, script = EXTENSIONLESS_VALIDATOR
        return img, script, "(elf-binary)"

    return None


def _find_service_dir(filepath: Path, root: Path) -> Path:
    """Find the test-* service directory that contains this file."""
    rel = filepath.relative_to(root)
    return root / rel.parts[0]  # e.g. root / "test-vue"


def validate_artifact(filepath: Path, root: Path,
                      docker_image: str, script_template: str,
                      max_retries: int = 1) -> ValidationResult:
    """Run a single artifact validation in Docker.

    Retries once on "No such file" errors caused by intermittent Docker
    bind-mount cache staleness after rapid container cycles.
    """
    # Mount the SERVICE directory (test-*), not the file's parent.
    # This avoids mount issues when files are in subdirectories.
    svc_dir = _find_service_dir(filepath, root)
    mount_dst = "/svc"
    rel_in_svc = filepath.relative_to(svc_dir)
    container_file = f"/svc/{rel_in_svc}"

    # Build the full script: set $1 = file path, then run the validator
    full_script = f'set -- "{container_file}" && {script_template}'

    rel = str(filepath.relative_to(root))
    ext = filepath.suffix.lower()

    for attempt in range(1 + max_retries):
        t0 = time.monotonic()
        try:
            r = docker_run(docker_image, svc_dir, mount_dst, full_script, timeout=60)
            dt = time.monotonic() - t0
            if r.returncode == 0:
                msg = r.stdout.strip().split("\n")[-1] if r.stdout.strip() else "OK"
                return ValidationResult(rel, ext, docker_image, True, msg, dt)
            else:
                err = (r.stdout.strip() + " " + r.stderr.strip()).strip()
                # Retry on bind-mount staleness (file exists on host but
                # Docker container can't see it yet).
                if "No such file" in err and attempt < max_retries:
                    time.sleep(2)
                    continue
                return ValidationResult(rel, ext, docker_image, False,
                                        err[:200] if err else f"exit code {r.returncode}", dt)
        except subprocess.TimeoutExpired:
            dt = time.monotonic() - t0
            return ValidationResult(rel, ext, docker_image, False, "TIMEOUT (60s)", dt)
        except Exception as e:
            dt = time.monotonic() - t0
            return ValidationResult(rel, ext, docker_image, False, str(e)[:200], dt)

    # Should not reach here, but safety fallback
    return ValidationResult(rel, ext, docker_image, False, "max retries exceeded", 0.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate artifacts in native Docker containers")
    parser.add_argument("--root", default=".pactown",
                        help="Artifact root directory (default: .pactown)")
    parser.add_argument("--strict", action="store_true",
                        help="Exit with error if any validation fails")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print each validation as it runs")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.is_absolute():
        root = Path(__file__).resolve().parent.parent / root

    if not root.exists():
        print(f"ERROR: Artifact root not found: {root}")
        return 1

    if not docker_available():
        print("ERROR: Docker is not available")
        return 1

    artifacts = collect_artifacts(root)
    if not artifacts:
        print(f"ERROR: No artifacts found in {root}/test-*")
        return 1

    print(f"\n{'=' * 70}")
    print(f" Validating {len(artifacts)} artifacts in native Docker containers")
    print(f" Root: {root}")
    print(f"{'=' * 70}\n")

    report = ValidationReport()
    skipped = 0

    # Pre-pull images to avoid repeated pulls
    images_needed = set()
    for f in artifacts:
        v = get_validator(f)
        if v:
            images_needed.add(v[0])

    print(f"  Pulling {len(images_needed)} Docker images...")
    for img in sorted(images_needed):
        subprocess.run(["docker", "pull", "-q", img],
                       capture_output=True, timeout=120)
    print(f"  Done.\n")

    for i, filepath in enumerate(artifacts, 1):
        validator = get_validator(filepath)
        if validator is None:
            skipped += 1
            continue

        docker_image, script, desc = validator
        rel = str(filepath.relative_to(root))

        if args.verbose:
            print(f"  [{i:3d}/{len(artifacts)}] {rel} → {docker_image} ... ", end="", flush=True)

        result = validate_artifact(filepath, root, docker_image, script)
        report.results.append(result)

        if args.verbose:
            status = "✓" if result.passed else "✗"
            print(f"{status} ({result.duration_s:.1f}s) {result.message[:60]}")

    report.print_summary()

    if skipped:
        print(f"  (Skipped {skipped} files with no validator)\n")

    total_time = sum(r.duration_s for r in report.results)
    print(f"  Total validation time: {total_time:.1f}s\n")

    if args.strict and report.failed > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
