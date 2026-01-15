# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
