from __future__ import annotations

from typing import Optional

# ---------------------------------------------------------------------------
# Block and parse_blocks are provided by the markpact base library.
# pactown re-exports them so that internal callers can keep using
#   ``from pactown.markpact_blocks import parse_blocks, Block``
# without changing any import paths.
# ---------------------------------------------------------------------------
from markpact.parser import Block, parse_blocks  # noqa: F401


def extract_target_config(blocks: list[Block]) -> Optional["TargetConfig"]:
    """Extract TargetConfig from markpact:target block if present."""
    for b in blocks:
        if b.kind == "target":
            from .targets import TargetConfig
            return TargetConfig.from_yaml_body(b.body)
    return None


def extract_build_cmd(blocks: list[Block]) -> Optional[str]:
    """Extract build command from markpact:build block if present."""
    for b in blocks:
        if b.kind == "build":
            cmd = b.body.strip()
            if cmd:
                return cmd
    return None


def extract_run_command(blocks: list[Block]) -> Optional[str]:
    """Extract run command from blocks, with framework inference fallback.

    Priority:
    1. Explicit ``markpact:run`` block
    2. ``default_run_cmd`` from the framework declared in ``markpact:target``
    3. File-based heuristic (main.py → ``python main.py``, etc.)
    """
    # 1. Explicit run block
    for b in blocks:
        if b.kind == "run":
            cmd = b.body.strip()
            if cmd:
                return cmd

    # 2. Framework default from markpact:target
    target_cfg = extract_target_config(blocks)
    if target_cfg is not None:
        meta = target_cfg.framework_meta
        if meta and meta.default_run_cmd:
            return meta.default_run_cmd

    # 3. File heuristic
    file_paths = [b.get_path() for b in blocks if b.kind == "file"]
    file_names = {(p or "").rsplit("/", 1)[-1] for p in file_paths if p}
    if "main.py" in file_names:
        return "python main.py"
    if "app.py" in file_names:
        return "python app.py"
    if "index.js" in file_names:
        return "node index.js"
    if "server.js" in file_names:
        return "node server.js"
    if "main.js" in file_names:
        return "node main.js"

    return None
