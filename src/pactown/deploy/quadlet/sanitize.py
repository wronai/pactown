"""Quadlet input sanitization."""
from __future__ import annotations

import re
from typing import Optional

# Safe characters for container/service names
SAFE_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$')

# Dangerous patterns that should never appear in unit files
DANGEROUS_PATTERNS = [
    r';\s*rm\s',
    r';\s*cat\s',
    r'\|\s*nc\s',
    r'\|\s*bash',
    r'\|\s*sh\b',
    r'\$\(',
    r'`[^`]+`',
    r'curl\s+[^|]*\|\s*bash',
    r'wget\s+[^|]*\|\s*bash',
]

# Blocked volume mounts for security
BLOCKED_VOLUME_PATHS = [
    '/etc/shadow',
    '/etc/passwd',
    '/etc/sudoers',
    '/root/.ssh',
    '/proc',
    '/sys',
    '/dev',
    '/var/run/docker.sock',
    '/run/podman/podman.sock',
]


def sanitize_name(name: str) -> str:
    """Sanitize container/service name to prevent injection.

    Only allows alphanumeric, underscore, and hyphen.
    Removes all dangerous characters and patterns.
    """
    if not name:
        return "unnamed"

    # Remove null bytes
    name = name.replace('\x00', '')

    # Remove newlines and carriage returns
    name = name.replace('\n', '').replace('\r', '')

    # Remove shell metacharacters
    for char in [';', '|', '&', '$', '`', '(', ')', '{', '}', '[', ']', '<', '>', '"', "'", '\\']:
        name = name.replace(char, '')

    # Remove path separators
    name = name.replace('/', '-').replace('..', '')

    # Only keep safe characters
    name = re.sub(r'[^a-zA-Z0-9_-]', '-', name)

    # Remove leading hyphens/underscores
    name = name.lstrip('-_')

    # Ensure it starts with alphanumeric
    if not name or not name[0].isalnum():
        name = 'svc-' + name

    # Limit length
    return name[:63]


def sanitize_env_value(value: str) -> str:
    """Sanitize environment variable value.

    Escapes special characters that could break INI format.
    """
    if not value:
        return ""

    # Remove null bytes
    value = value.replace('\x00', '')

    # Escape newlines (critical for INI injection prevention)
    value = value.replace('\n', '\\n').replace('\r', '\\r')

    # Don't allow section headers
    value = re.sub(r'\[(\w+)\]', r'(\1)', value)

    return value


def sanitize_env_key(key: str) -> str:
    """Sanitize environment variable key.

    Only allows alphanumeric and underscore.
    """
    if not key:
        return "INVALID_KEY"

    # Remove null bytes and newlines
    key = key.replace('\x00', '').replace('\n', '').replace('\r', '')

    # Only keep safe characters for env var names
    key = re.sub(r'[^a-zA-Z0-9_]', '_', key)

    # Must start with letter or underscore
    if key and key[0].isdigit():
        key = '_' + key

    return key[:128]


def sanitize_path(path: str) -> str:
    """Sanitize file/volume path.

    Prevents path traversal attacks.
    """
    if not path:
        return ""

    # Remove null bytes
    path = path.replace('\x00', '')

    # Remove newlines
    path = path.replace('\n', '').replace('\r', '')

    # Remove shell metacharacters from path
    for char in [';', '|', '&', '$', '`', '(', ')', '<', '>']:
        path = path.replace(char, '')

    return path


def sanitize_domain(domain: str) -> str:
    """Sanitize domain name.

    Only allows valid domain characters.
    """
    if not domain:
        return "localhost"

    # Remove null bytes and newlines
    domain = domain.replace('\x00', '').replace('\n', '').replace('\r', '')

    # Remove injection attempts
    for char in ['`', ')', '(', '"', "'", '\\', ';', '|', '&', '$', '{', '}']:
        domain = domain.replace(char, '')

    # Only keep valid domain characters
    domain = re.sub(r'[^a-zA-Z0-9.-]', '', domain)

    return domain[:253]


def sanitize_image(image: str) -> str:
    """Sanitize container image name.

    Only allows valid image reference characters.
    """
    if not image:
        return "nginx:latest"

    # Remove null bytes and newlines
    image = image.replace('\x00', '').replace('\n', '').replace('\r', '')

    # Remove shell metacharacters
    for char in [';', '|', '&', '$', '`', '(', ')', '<', '>', '"', "'", '\\', ' ']:
        image = image.replace(char, '')

    # Only keep valid image reference characters
    # Format: [registry/][namespace/]name[:tag][@digest]
    image = re.sub(r'[^a-zA-Z0-9._:/@-]', '', image)

    return image[:255]


def sanitize_health_check(endpoint: str) -> str:
    """Sanitize health check endpoint.

    Only allows safe URL path characters.
    """
    if not endpoint:
        return "/health"

    # Remove null bytes and newlines
    endpoint = endpoint.replace('\x00', '').replace('\n', '').replace('\r', '')

    # Remove shell metacharacters
    for char in [';', '|', '&', '$', '`', '(', ')', '<', '>', '"', "'", '\\']:
        endpoint = endpoint.replace(char, '')

    # Must start with /
    if not endpoint.startswith('/'):
        endpoint = '/' + endpoint

    # Only keep valid URL path characters
    endpoint = re.sub(r'[^a-zA-Z0-9/_.-]', '', endpoint)

    return endpoint[:255]


def validate_volume(volume: str) -> tuple[bool, str]:
    """Validate volume mount specification.

    Returns (is_valid, sanitized_volume or error message).
    """
    if not volume:
        return False, "Empty volume specification"

    # Remove null bytes first
    volume = volume.replace('\x00', '')

    # CRITICAL: Check for newline injection before anything else
    if '\n' in volume or '\r' in volume:
        return False, "Newline injection detected"

    # Sanitize path
    volume = sanitize_path(volume)

    # Check for blocked paths
    for blocked in BLOCKED_VOLUME_PATHS:
        if blocked in volume:
            return False, f"Blocked path: {blocked}"

    # Check for path traversal
    if '..' in volume:
        return False, "Path traversal detected"

    return True, volume


def check_dangerous_content(content: str) -> list[str]:
    """Check content for dangerous patterns.

    Returns list of detected dangerous patterns.
    """
    found = []
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            found.append(pattern)
    return found

