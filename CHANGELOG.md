# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-01-16

### Added

- **Fast Start Module** (`fast_start.py`)
  - Dependency caching with hash-based venv reuse
  - ~50-100ms startup for cached deps vs ~5-10s fresh
  - `ServiceRunner.fast_run()` method
  - Parallel file writing for sandbox creation

- **Security Policy Module** (`security.py`)
  - Rate limiting with token bucket algorithm
  - User profiles with tier-based limits (FREE/BASIC/PRO/ENTERPRISE)
  - Concurrent service limits per user
  - Anomaly logging for admin monitoring
  - Server load throttling

- **User Isolation Module** (`user_isolation.py`)
  - Linux user-based sandbox isolation
  - Per-SaaS-user home directories
  - Process isolation with different UIDs
  - Export/import for user data migration
  - REST API endpoints for user management

- **Detailed Logging**
  - Structured logging in sandbox_manager
  - STDERR/STDOUT capture on process failure
  - Signal interpretation (SIGTERM, SIGKILL, etc.)
  - Per-service error log files

- **New Documentation**
  - `docs/FAST_START.md` - Dependency caching guide
  - `docs/SECURITY_POLICY.md` - Rate limiting and user profiles
  - `docs/USER_ISOLATION.md` - Multi-tenant isolation
  - `docs/LOGGING.md` - Structured logging guide
  - Navigation links across all docs

- **New Examples**
  - `examples/fast-start-demo/` - Fast startup with caching
  - `examples/security-policy/` - Rate limiting demo
  - `examples/user-isolation/` - Multi-tenant isolation demo

### Changed

- README.md restructured with feature menu and quick navigation
- All docs updated with cross-links for easier navigation
- sandbox_manager.py: Better error capture and signal handling
- service_runner.py: Added delays to prevent race conditions on restart

### Fixed

- Process killed by SIGTERM on restart (race condition)
- Truncated error output from crashed processes
- **Hardcoded port mismatch** - Auto-replace hardcoded ports (e.g., `--port 8009`) with requested port
- PORT and MARKPACT_PORT environment variables now always set

## [Unreleased]

### Added

- Podman Quadlet deployment backend (`pactown.deploy.quadlet`) with templates, backend operations, and Traefik integration.
- Interactive Quadlet shell (`pactown quadlet shell`).
- Quadlet REST API (`pactown quadlet api`) and entrypoint `pactown-quadlet-api`.
- Security hardening and injection test suite (`tests/test_quadlet_security.py`).
- Quadlet security guide (`docs/SECURITY.md`).
- Cloudflare Workers comparison (`docs/CLOUDFLARE_WORKERS_COMPARISON.md`).
- Practical Quadlet examples in `examples/*` where the user edits only `README.md` (embedded code blocks) and deployment artifacts are generated into `./sandbox`.

### Changed

- Dockerfile Python healthcheck now uses `MARKPACT_PORT` with fallback to `PORT` to maintain compatibility.
- Registry timestamps use timezone-aware datetimes (`datetime.now(timezone.utc)`) to avoid Python 3.13 deprecations.
- Makefile:
  - Prefers project venv python if present.
  - `lint`/`format` fall back to `pipx run ruff` when ruff is not installed in the interpreter.
  - `test` explicitly loads `pytest_asyncio.plugin` to work with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`.

### Fixed

- Multiple Quadlet injection vectors (container name, env var, volume, Traefik label, systemd unit) mitigated via input sanitization.
- Ruff lint issues across `src/` and `tests/`.

## [0.1.5]

- Initial public version.
