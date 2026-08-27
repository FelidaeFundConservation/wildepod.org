# Configuration & Secrets Guide

This document explains where real configuration values are stored and how the
application loads them at runtime. No actual secrets or project identifiers are
committed to this repository.

---

## Principle: Never commit real values to source code

The codebase uses placeholders (e.g., `<YOUR-PROJECT-ID>`) everywhere a real
infrastructure identifier or secret would otherwise appear. Real values live in
one of two places depending on context:

| Context | Where values live |
|---------|------------------|
| GitHub Actions CI/CD | GitHub repository **Variables** and **Secrets** |
| Running app (prod/staging/bhutan) | **GCP Secret Manager** (loaded automatically at startup) |
| Local development | Your personal `.env` file (never committed) |
| Deploy scripts (run manually) | Shell environment variables exported before running |

---

## 1 · GitHub Actions — Variables and Secrets

Variables and secrets are set in the repository under:
**Settings → Secrets and variables → Actions**

### Variables (non-sensitive, visible in logs)

| Variable name | Description | Example value |
|---------------|-------------|---------------|
| `GCP_PROJECT_ID` | GCP project identifier | `myorg-project-123` |
| `GCP_DB_INSTANCE` | Cloud SQL instance name | `myprojectdb` |
| `GCP_REGION` | Default GCP region | `us-west2` |
| `STAGING_SETTINGS_NAME` | Secret Manager secret name for staging | `django_settings` |

Reference in workflows as `${{ vars.GCP_PROJECT_ID }}`.

### Secrets (sensitive, redacted in logs)

| Secret name | Description |
|-------------|-------------|
| `GCP_SA_KEY` | Service account JSON key for GitHub Actions authentication |

Reference in workflows as `${{ secrets.GCP_SA_KEY }}`.

---

## 2 · GCP Secret Manager — Runtime app configuration

When deployed to App Engine, the application loads all settings from a single
secret stored in GCP Secret Manager. This secret is a `.env`-format text blob
containing every environment variable the application needs.

**Secret name:** `django_settings` (configurable via `SETTINGS_NAME` env var)

**How to view/update the secret:**
```bash
# View current value
gcloud secrets versions access latest --secret=django_settings --project=<YOUR-PROJECT-ID>

# Update with a new version (pipe a new .env-format file)
gcloud secrets versions add django_settings \
  --data-file=path/to/new-settings.env \
  --project=<YOUR-PROJECT-ID>
```

### Required variables in the secret

The secret must contain at minimum:

```env
DJANGO_SECRET_KEY=<generated-secret-key>
ADMIN_URL_SUFFIX=<random-suffix>
GOOGLE_CLOUD_PROJECT=<YOUR-PROJECT-ID>

# Export trigger URL token — generate with:
# python -c "import secrets; print(secrets.token_urlsafe(18))"
EXPORT_URL_SUFFIX=<generated-random-token>

# Database
PROD_DATABASE_URL=******//cloudsql/<YOUR-PROJECT-ID>:<region>:<YOUR-DB-INSTANCE>/prod
STAGING_DATABASE_URL=******//cloudsql/<YOUR-PROJECT-ID>:<region>:<YOUR-DB-INSTANCE>/staging

# Cloud Storage
GS_BUCKET_NAME_PROD=<your-prod-bucket>
GS_BUCKET_NAME_STAGING=<your-staging-bucket>

# ML inference
MEGADETECTOR_URL=https://<your-cloud-run-url>
SPECIES_DETECTOR_URL=https://<region>-<YOUR-PROJECT-ID>.cloudfunctions.net/<function-name>

# Email
MAILGUN_SMTP_PASSWORD=<mailgun-password>

# Dropbox
DROPBOX_APP_KEY_PROD=<key>
DROPBOX_APP_SECRET_PROD=<secret>
DROPBOX_REFRESH_TOKEN_PROD=<token>
```

---

## 3 · Local development — `.env` file

For local development, copy `.env.local.example` to `.env` and fill in values:

```bash
cp .env.local.example .env
# Edit .env with your local values
```

The `.env` file is listed in `.gitignore` and must never be committed.

For GCP-dependent features locally, ask a team member for the current values
from Secret Manager or your team's shared password manager.

---

## 4 · Deploy scripts — shell environment variables

The `deploy_custom.sh` and `post_deploy_setup.sh` scripts require these to be
exported in your shell before running:

```bash
export GCP_PROJECT_ID=<YOUR-PROJECT-ID>
export GCP_DB_INSTANCE=<YOUR-DB-INSTANCE>
export GCP_REGION=us-west2          # optional, defaults to us-west2

# Then run:
./deploy_custom.sh <your-name>-dev --use-existing-db --db-instance $GCP_DB_INSTANCE --full
./post_deploy_setup.sh <your-name>-dev
```

You can persist these in a local `.deploy.config` file (see `deploy.config.example`)
and `source` it before deploying. The `.deploy.config` file is listed in
`.gitignore` and must never be committed.

---

## 5 · EXPORT_URL_SUFFIX — why it's a secret

The `EXPORT_URL_SUFFIX` is a random token embedded in the URL path of the
internal export-job trigger endpoint (`/exports/start/<token>/`). It functions
as a shared secret so that the endpoint is not discoverable by outside parties.

**It must be stored in Secret Manager** (included in the `django_settings`
secret) and never hardcoded in source code. Rotate it by updating the secret
and redeploying.

---

## 6 · Repository secret audit and cleanup

During the repository review for issue #533, no credible live credentials were
found in the tracked source tree or git history. The only password-like value
in committed source was a local-only default superuser password in
`local_setup.sh`, which has been removed.

### Quick audit commands

Use these commands before pushing changes:

```bash
# Current working tree
grep -RInE 'AKIA[0-9A-Z]{16}|ghp_|github_pat_|xox[baprs]-|-----BEGIN (RSA|OPENSSH|DSA|EC|PGP) PRIVATE KEY-----' .

# Existing repo safety checks
./pre_deploy_check.sh local

# Git history for high-signal secret patterns
git log --all --oneline -G 'AKIA[0-9A-Z]{16}|ghp_|github_pat_|xox[baprs]-|-----BEGIN (RSA|OPENSSH|DSA|EC|PGP) PRIVATE KEY-----'
```

### If a real secret is found

1. **Revoke or rotate it immediately** in the upstream system:
   - GitHub token → revoke it in GitHub
   - GCP service-account key or Secret Manager value → disable/rotate it in GCP
   - Dropbox/Mailgun/database credentials → rotate them with that provider
2. **Remove it from the current tree** and replace it with a placeholder or a
   Secret Manager / GitHub Actions secret reference.
3. **Rewrite git history** if the secret was ever committed:

   ```bash
   pipx run git-filter-repo --path path/to/file --invert-paths
   ```

   Or, for a string replacement across history, use a replacements file with
   `git-filter-repo --replace-text`.
4. **Force-push the rewritten branch** and ask other collaborators to rebase or
   re-clone, because old commits will still contain the secret locally.
5. **Invalidate any cached copies** (CI logs, deployment artifacts, copied
   `.env` files, screenshots, shared snippets).
6. **Confirm the cleanup** by re-running the working tree and history scans
   above after the rotation is complete.
