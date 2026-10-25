# Python 3.14 Migration Strategy (Issue #542)

This document defines a migration plan to move WildePod from Python 3.10 to Python 3.14, including dependency and verification guidance.

## Scope

- Runtime and tooling baseline moves to Python 3.14.
- CI and deployment workflows run on Python 3.14.
- App Engine services run with `python314`.

## Dependency update plan

### 1) Baseline sync on Python 3.14

1. Update project/runtime declarations:
   - `pyproject.toml` (`requires-python`, formatter/type-check targets)
   - `.python-version`
   - GitHub workflows
   - App Engine runtime yaml files
2. Regenerate lock/exports on Python 3.14:
   - `uv lock`
   - `uv export --no-hashes -o requirements.txt`
   - `uv export --no-hashes --all-extras -o requirements-dev.txt`

### 2) Relevant package compatibility pass

Validate and, if needed, update these high-impact packages first:

- **Django** (`django`)
- **WSGI server** (`gunicorn`)
- **Numerics/data stack** (`numpy`, `pandas`)
- **Auth/security** (`argon2-cffi`, `cryptography`)
- **Database/runtime edges** (`psycopg2-binary`)

Recommendation: prefer minimal, compatible version bumps rather than major jumps, and upgrade one compatibility group at a time.

## Testing and verification strategy

### 1) Fast local checks

- `uv sync --extra dev`
- `uv run pytest -q` (or targeted app tests first)
- `uv run flake8`
- `uv run python manage.py check --settings=config.settings.ci`

### 2) Django safety checks

- `uv run python manage.py makemigrations --check --dry-run`
- `uv run python manage.py migrate --plan --settings=config.settings.staging`
- `uv run python manage.py collectstatic --noinput --settings=config.settings.ci`

### 3) CI workflow validation

- Run PR workflow on Python 3.14 (`.github/workflows/pr-build.yml`).
- Run staging deploy workflow in dry-run mode first.
- Validate migration plan output and static collection artifact generation.

### 4) Rollout

1. Deploy staging (`staging.yaml`) and monitor logs/errors.
2. Run production deployment as dry-run.
3. Deploy production/bhutan after staging is stable.

## Potential breaking API/runtime changes to consider

- **Stdlib removals/deprecations in 3.14**: any legacy imports/APIs removed between 3.10 and 3.14 can break at runtime; run full test coverage plus Django management checks.
- **Binary wheels/ABI**: packages with native extensions (for example `numpy`, `psycopg2-binary`, `cryptography`) must provide Python 3.14 wheels in CI/deploy environment.
- **Django compatibility window**: confirm the pinned Django series supports Python 3.14; if not, update to a supported patch/minor release and rerun migration/test steps.
- **Gunicorn runtime behavior**: newer gunicorn versions may change defaults around worker behavior/signals; verify startup, health checks, and long-running request handling.

## Definition of done

- All configured Python versions/runtime targets are 3.14.
- Lock/export files are reproducible from Python 3.14.
- PR CI passes on Python 3.14.
- Staging deployment + migration checks pass with no new runtime errors.
