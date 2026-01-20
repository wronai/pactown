import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest

from pactown.config import ServiceConfig
from pactown.sandbox_manager import SandboxManager

def test_sandbox_manager_passes_env_to_node_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sandbox_root = tmp_path / "sandboxes"
    manager = SandboxManager(sandbox_root)

    # Mock DependencyCache to avoid real caching logic
    if manager._dep_cache:
        monkeypatch.setattr(manager._dep_cache, "get_cached_venv", lambda _deps: None)

    # Mock ensure_venv to do nothing (we don't need a real venv for this test)
    monkeypatch.setattr("pactown.sandbox_manager.ensure_venv", lambda *args, **kwargs: None)

    # Capture the environment passed to Popen
    captured = {}

    def fake_popen(cmd, stdout=None, stderr=None, text=False, bufsize=0, env=None, **kwargs):
        cmd_str = str(cmd) if isinstance(cmd, str) else " ".join(cmd)
        # Check if it's the run command (node index.js)
        if "node index.js" in cmd_str:
            captured["run_env"] = dict(env or {})
            
            # Simulate immediate exit
            proc = MagicMock()
            proc.poll.return_value = 0
            proc.returncode = 0
            proc.communicate.return_value = (b"", b"")
            proc.pid = 1234
            return proc
            
        # Default mock for other calls (like npm install)
        proc = MagicMock()
        proc.poll.return_value = 0
        proc.wait.return_value = 0
        proc.returncode = 0
        proc.communicate.return_value = (b"", b"")
        return proc

    monkeypatch.setattr("pactown.sandbox_manager.subprocess.Popen", fake_popen)
    # Also mock run for npm install checks if any
    monkeypatch.setattr("pactown.sandbox_manager.subprocess.run", 
                        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""))

    readme = """
```javascript markpact:file path=index.js
console.log(process.env.SUPABASE_URL);
```

```text markpact:deps
express
```

```bash markpact:run
node index.js
```
"""
    readme_path = tmp_path / "README.md"
    readme_path.write_text(readme)

    service = ServiceConfig(name="node-svc", readme=str(readme_path), port=8000)

    # Test environment variables
    test_env = {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_ANON_KEY": "secret-key"
    }

    # Run start_service
    manager.start_service(
        service=service,
        readme_path=readme_path,
        env=test_env,
        verbose=True
    )

    # Assertions
    assert "run_env" in captured, "Popen was not called for the run command"
    env_passed = captured["run_env"]
    
    assert env_passed.get("SUPABASE_URL") == "https://example.supabase.co"
    assert env_passed.get("SUPABASE_ANON_KEY") == "secret-key"
    assert env_passed.get("PORT") == "8000"
