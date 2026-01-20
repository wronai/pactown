# TODO

## Status (done)

- Pactown jako paczka Python (`pyproject.toml`, CLI, Makefile).
- Orchestrator (sandboxes), dependency resolution, registry + API.
- Podman Quadlet deployment:
  - `pactown quadlet init / deploy / list / logs / shell / api`
  - Traefik + TLS (Let's Encrypt)
- Security hardening:
  - input sanitization w generatorze Quadlet
  - test suite: `tests/test_quadlet_security.py`
  - dokument: `docs/SECURITY.md`
- Przykłady Quadlet w `examples/*`:
  - user edytuje tylko `README.md` (kod w markdown)
  - reszta plików do uruchomienia jest generowana do `./sandbox`

## Next steps

### Quadlet / Sandbox generation

- Zintegrować generowanie `./sandbox` z README (code blocks `main.py`, `routes.yaml`, `requirements.txt`) bezpośrednio w flow `pactown quadlet deploy`.
- Dodać walidację, że README zawiera minimalny zestaw blocków wymaganych do uruchomienia.
- Dodać tryb `pactown quadlet generate --sandbox ./sandbox` (bez deployu) do łatwego review.

### Security (runtime)

- Dodać runtime-hardening checklist: SELinux/AppArmor, firewall, limits per tenant.
- Rozważyć blokowanie dodatkowych mountów (symlinki, `:Z`, `:suid`, itp.) oraz logowanie prób.

### Docs

- Uporządkować przewodnik: `docs/QUADLET.md` + `docs/SECURITY.md` + porównanie z CF.
- Dodać krótkie “quick examples” jak odpalić 3 przykłady na VPS.

### Packaging

- Ustalić docelowy flow dla `make dev` i `make lint` (czy zawsze venv, czy pipx fallback).



Trzeba zrobić reprezentację IaC wszystkich generowanycch  środowisk w sandboxach
aby był ustandaryzowany format określacjący techstack, CI CD dla kążdego uruchamianego sandboxa
na poczatek może to być opis w formacie Dockerfile / docker compose, ale zapropopnuj na bazie tego co mamy aktualnie jakieś rozwiązanie
aby zejść z kodu imperatywnego w python na deklaratywnych w ustandaryzowanej formie IaC
aby podczas uruchamiania róznych sandboxów móc lepiej stwierdzić, gdzie pojawiają się błedy
oraz móc łatwiej testować i zabezpieczyć środowiska

wykorzystaj pliki indeksujące projektu z których będziesz korzystał aby rozwinąć pactown
/home/tom/github/wronai/pactown/project.functions.toon
/home/tom/github/wronai/pactown-com/project.functions.toon