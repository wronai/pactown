import os
import sys
import shutil
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from pactown.config import ServiceConfig
from pactown.sandbox_manager import SandboxManager
from pactown.fast_start import CachedVenv

def test_self_heal_corrupted_cache(tmp_path: Path, caplog):
    """
    Regression test for self-healing corrupted venv cache.
    Scenario:
    1. A venv exists in cache.
    2. 'Restoring' it succeeds (copy works).
    3. But verification fails (simulate broken import or bad python).
    4. Expectation: Manager should log warning, invalidate cache, and trigger full rebuild (pip install).
    """
    caplog.set_level(logging.DEBUG)
    
    # Setup directories
    sandbox_root = tmp_path / "sandboxes"
    cache_dir = tmp_path / "cache"
    sandbox_root.mkdir()
    cache_dir.mkdir()
    
    # Initialize manager
    manager = SandboxManager(sandbox_root)
    # Ensure dep_cache is active
    if manager._dep_cache is None:
        pytest.skip("DependencyCache not enabled/initialized in SandboxManager")

    # Construct a "corrupted" cached venv
    deps = ["fastapi"]
    deps_hash = manager._dep_cache._hash_deps(deps)
    
    # Fix: use cache_root instead of cache_dir
    cached_venv_path = manager._dep_cache.cache_root / f"venv_{deps_hash}"
    cached_venv_path.mkdir(parents=True, exist_ok=True)
    
    # Create a fake python binary so is_valid() returns True and exists check passes
    bin_dir = cached_venv_path / "bin"
    bin_dir.mkdir()
    python_exe = bin_dir / "python"
    python_exe.touch(mode=0o755)
    
    # Register in cache manually
    cached_entry = CachedVenv(
        deps_hash=deps_hash,
        path=cached_venv_path,
        created_at=0.0,
        last_used=0.0,
        deps=deps
    )
    with manager._dep_cache._lock:
        manager._dep_cache._cache[deps_hash] = cached_entry

    # Create README with these deps
    readme_content = """
```python markpact:deps
fastapi
```

```bash markpact:run
python main.py
```
"""
    readme_path = tmp_path / "README.md"
    readme_path.write_text(readme_content)
    
    service = ServiceConfig(name="test-service", readme=str(readme_path), port=8000)

    # Monkeypatch invalidate to ensure it's called and debug
    real_invalidate = manager._dep_cache.invalidate
    
    invalidate_called = []
    
    def patched_invalidate(deps):
        print(f"DEBUG: patched_invalidate called with {deps}")
        invalidate_called.append(deps)
        h = manager._dep_cache._hash_deps(deps)
        print(f"DEBUG: hash to invalidate: {h}")
        print(f"DEBUG: cache keys before: {list(manager._dep_cache._cache.keys())}")
        real_invalidate(deps)
        print(f"DEBUG: cache keys after: {list(manager._dep_cache._cache.keys())}")
            
    manager._dep_cache.invalidate = patched_invalidate

    # Mock subprocess.run to simulate verification failure
    # and mock subprocess.Popen to avoid real pip install.
    with patch("pactown.sandbox_manager.subprocess.run") as mock_run, \
         patch("pactown.sandbox_manager.subprocess.Popen") as mock_popen, \
         patch("pactown.sandbox_manager.ensure_venv") as mock_ensure_venv:
        
        def ensure_venv_side_effect(sandbox, **kwargs):
            # Create dummy pip so subprocess doesn't fail
            bin_dir = sandbox.venv_bin
            bin_dir.mkdir(parents=True, exist_ok=True)
            pip_path = bin_dir / "pip"
            # Write a valid script content so it can be executed
            with open(pip_path, "w") as f:
                f.write("#!/bin/sh\\nexit 0\\n")
            pip_path.chmod(0o755)
            
            # Also python for good measure
            python_path = bin_dir / "python"
            with open(python_path, "w") as f:
                f.write("#!/bin/sh\\nexit 0\\n")
            python_path.chmod(0o755)
            
        mock_ensure_venv.side_effect = ensure_venv_side_effect
        
        def side_effect(cmd, **kwargs):
            cmd_str = str(cmd)
            # If checking python imports (verification step)
            if "import importlib" in cmd_str:
                # Simulate failure (returncode 1)
                return MagicMock(returncode=1, stderr="ImportError: No module named fastapi")

            # Default success
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect

        proc = MagicMock()
        proc.stdout = []
        proc.wait.return_value = 0
        mock_popen.return_value = proc

        # Run create_sandbox
        print(f"\\nTest Setup: Deps Hash = {deps_hash}")
        print(f"Test Setup: Cache Keys = {list(manager._dep_cache._cache.keys())}")
        
        sandbox = manager.create_sandbox(
            service=service,
            readme_path=readme_path,
            install_dependencies=True
        )

        # Assertions
        
        # 1. Check if "Cached venv verification failed" is in logs
        if "Cached venv verification failed" not in caplog.text:
            print("LOGS CAPTURED:")
            print(caplog.text)
        assert "Cached venv verification failed" in caplog.text
        assert "Cached venv appears corrupted - rebuilding" in caplog.text
        
        # 2. Verify invalidate was called
        assert invalidate_called
        assert invalidate_called[-1] == deps
        
        # 3. Cache should be re-created after rebuild
        with manager._dep_cache._lock:
            cached_entry = manager._dep_cache._cache.get(deps_hash)

        print(f"Post-Test: Cache Keys = {list(manager._dep_cache._cache.keys())}")

        assert cached_entry is not None
        assert cached_entry.created_at > 0
        assert cached_entry.path.exists()
        deps_file = cached_entry.path / ".deps"
        assert deps_file.exists()
        assert "fastapi" in deps_file.read_text(encoding="utf-8")

        
        # 3. Check if rebuild happened
        # ensure_venv should be called
        mock_ensure_venv.assert_called()
        
        # pip install should be called
        pip_called = any(
            (call.args and isinstance(call.args[0], list) and call.args[0] and "install" in call.args[0] and "pip" in str(call.args[0][0]))
            for call in mock_popen.call_args_list
        )
        assert pip_called, "Should have triggered pip install after invalidation"
