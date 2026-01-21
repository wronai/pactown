import argparse
import re
from pathlib import Path


def _read_pactown_version(pyproject_path: Path) -> str:
    text = pyproject_path.read_text(encoding="utf-8")
    m = re.search(r"(?m)^version\s*=\s*\"([^\"]+)\"\s*$", text)
    if not m:
        raise RuntimeError(f"Could not find version in {pyproject_path}")
    return m.group(1).strip()


def _update_requirements_pin(req_path: Path, *, version: str) -> bool:
    lines = req_path.read_text(encoding="utf-8").splitlines(keepends=True)
    changed = False
    found = False

    out: list[str] = []
    for line in lines:
        m = re.match(r"^(\s*)pactown\s*==\s*([^\s#]+)(\s*)(#?.*)$", line)
        if m:
            found = True
            prefix, _old_version, mid_ws, trailing = m.groups()
            newline = "\n"
            if line.endswith("\r\n"):
                newline = "\r\n"
            elif line.endswith("\n"):
                newline = "\n"
            replacement = f"{prefix}pactown=={version}{mid_ws}{trailing}{newline}"
            if replacement != line:
                changed = True
            out.append(replacement)
        else:
            out.append(line)

    if not found:
        raise RuntimeError(f"No 'pactown==...' pin found in {req_path}")

    if changed:
        req_path.write_text("".join(out), encoding="utf-8")

    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pactown-root", default=None)
    parser.add_argument("--pactown-com-root", default=None)
    parser.add_argument("--requirements", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    script_path = Path(__file__).resolve()
    pactown_root = Path(args.pactown_root).resolve() if args.pactown_root else script_path.parents[1]
    pactown_com_root = (
        Path(args.pactown_com_root).resolve()
        if args.pactown_com_root
        else Path((pactown_root.parent / "pactown-com").as_posix()).resolve()
    )

    pyproject_path = pactown_root / "pyproject.toml"
    version = _read_pactown_version(pyproject_path)

    req_rel = Path(args.requirements) if args.requirements else Path("backend/requirements.txt")
    req_path = (pactown_com_root / req_rel).resolve()

    if not req_path.exists():
        raise RuntimeError(f"Requirements file not found: {req_path}")

    if args.dry_run:
        content = req_path.read_text(encoding="utf-8")
        if re.search(r"(?m)^\s*pactown\s*==\s*" + re.escape(version) + r"\s*(#.*)?$", content):
            print(f"OK: {req_path} already has pactown=={version}")
            return 0
        print(f"Would update {req_path} to pactown=={version}")
        return 0

    changed = _update_requirements_pin(req_path, version=version)
    if changed:
        print(f"Updated {req_path} to pactown=={version}")
    else:
        print(f"No change needed: {req_path} already has pactown=={version}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
