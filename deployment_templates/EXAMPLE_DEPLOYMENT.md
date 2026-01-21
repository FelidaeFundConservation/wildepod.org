# Example: Custom Development Environment Configuration

This example shows how to create a custom development environment called "alice-dev" using the deployment templates.

## Prerequisites

- GCP project: wildepod-339517
- Existing Cloud SQL instance: wildepoddb (shared)
- Access to Secret Manager

## Step-by-Step Example

### 1. Decide on Environment Name

Choose a descriptive name following the naming rules:
- Lowercase letters, numbers, hyphens only
- Start and end with letter or number
- 1-63 characters

Example: `alice-dev`

### 2. Option A: Automated Deployment (Recommended)

Use the deployment script to auto-generate all files:

```bash
# Create custom environment with shared database
./deploy_custom.sh alice-dev --use-existing-db --db-instance wildepoddb --full

# Run post-deployment setup
./post_deploy_setup.sh alice-dev
```

This creates:
- `config/settings/alice-dev.py`
- `config/wsgi/alice-dev.py`
- `alice-dev.yaml`
- `alice-dev.py`

### 2. Option B: Manual Deployment (Advanced)

If you need to customize files before deployment:

#### Copy and rename template files:

```bash
# Settings
cp deployment_templates/TEMPLATE_config_settings.py config/settings/alice-dev.py

# WSGI
cp deployment_templates/TEMPLATE_config_wsgi.py config/wsgi/alice-dev.py

# App Engine YAML
cp deployment_templates/TEMPLATE_app_yaml.yaml alice-dev.yaml

# Entry point
cp deployment_templates/TEMPLATE_entry_point.py alice-dev.py
```

#### Replace placeholders in each file:

**In `config/settings/alice-dev.py`:**
- `<ENV_NAME>` → `ALICE_DEV`
- `<env-name>` → `alice-dev`
- `<DATABASE_URL_VAR>` → `ALICE_DEV_DATABASE_URL`

**In `config/wsgi/alice-dev.py`:**
- `<env-name>` → `alice-dev`

**In `alice-dev.yaml`:**
- `<env-name>` → `alice-dev`
- `<instance-class>` → `F1` (or F2, F4, etc.)

**In `alice-dev.py`:**
- `<env-name>` → `alice-dev`

### 3. Set Up Secrets in Secret Manager

Create database connection string secret:

```bash
# For new dedicated database
gcloud secrets create ALICE_DEV_DATABASE_URL \
  --data-file=- <<EOF
postgres://wildepod_user:PASSWORD@/wildepod_alice_dev?host=/cloudsql/wildepod-339517:us-west2:wildepoddb-alice-dev
EOF

# OR for shared database (recommended for dev)
gcloud secrets create ALICE_DEV_DATABASE_URL \
  --data-file=- <<EOF
postgres://wildepod_user:PASSWORD@/wildepod_alice_dev?host=/cloudsql/wildepod-339517:us-west2:wildepoddb
EOF
```

Create Dropbox secrets (environment-specific):

```bash
gcloud secrets create DROPBOX_APP_KEY_ALICE_DEV --data-file=- <<EOF
your-dropbox-app-key-here
EOF

gcloud secrets create DROPBOX_APP_SECRET_ALICE_DEV --data-file=- <<EOF
your-dropbox-app-secret-here
EOF

gcloud secrets create DROPBOX_REFRESH_TOKEN_ALICE_DEV --data-file=- <<EOF
your-dropbox-refresh-token-here
EOF
```

Grant App Engine access to secrets:

```bash
# Get App Engine service account
PROJECT_ID="wildepod-339517"
SERVICE_ACCOUNT="${PROJECT_ID}@appspot.gserviceaccount.com"

# Grant access to secrets
gcloud secrets add-iam-policy-binding ALICE_DEV_DATABASE_URL \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding DROPBOX_APP_KEY_ALICE_DEV \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding DROPBOX_APP_SECRET_ALICE_DEV \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding DROPBOX_REFRESH_TOKEN_ALICE_DEV \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/secretmanager.secretAccessor"
```

### 4. Create Database (if using shared instance)

```bash
# Connect to existing Cloud SQL instance
gcloud sql connect wildepoddb --user=postgres --database=postgres

# In psql, create database
CREATE DATABASE wildepod_alice_dev;
GRANT ALL PRIVILEGES ON DATABASE wildepod_alice_dev TO wildepod_user;
\q
```

### 5. Deploy to App Engine

```bash
# Deploy the service
gcloud app deploy alice-dev.yaml

# Verify deployment
gcloud app browse -s alice-dev
```

### 6. Run Post-Deployment Setup

```bash
# Migrate database and create superuser
./post_deploy_setup.sh alice-dev
```

## Verification

Check that your environment is running:

```bash
# Get service URL
gcloud app browse -s alice-dev

# Check logs
gcloud app logs tail -s alice-dev

# Test admin access
# https://alice-dev-dot-wildepod-339517.appspot.com/admin/
```

## Cost Estimate

Using shared database with F1 instance:
- App Engine F1: ~$0.05/day (~$1.50/month)
- Database (shared): $0 (already running)
- Storage: ~$0.02/GB/month
- **Total: < $2/month**

## Cleanup

When done with the environment:

```bash
# Delete the service
gcloud app services delete alice-dev

# Delete the database (if dedicated)
gcloud sql databases delete wildepod_alice_dev --instance=wildepoddb-alice-dev

# Delete the Cloud SQL instance (if dedicated)
gcloud sql instances delete wildepoddb-alice-dev

# Delete secrets
gcloud secrets delete ALICE_DEV_DATABASE_URL
gcloud secrets delete DROPBOX_APP_KEY_ALICE_DEV
gcloud secrets delete DROPBOX_APP_SECRET_ALICE_DEV
gcloud secrets delete DROPBOX_REFRESH_TOKEN_ALICE_DEV

# Remove local files
rm -f config/settings/alice-dev.py
rm -f config/wsgi/alice-dev.py
rm -f alice-dev.yaml
rm -f alice-dev.py
```

## Troubleshooting

### Build fails with "No module named 'config.settings.alice-dev'"
- Check that `config/settings/alice-dev.py` exists
- Verify WSGI_APPLICATION setting points to correct path
- Ensure all placeholders were replaced

### Database connection fails
- Verify database URL secret is correct
- Check database exists: `gcloud sql databases list --instance=wildepoddb`
- Confirm App Engine has secretAccessor role

### Service not found after deployment
- Check service exists: `gcloud app services list`
- Verify deployment succeeded: `gcloud app versions list --service=alice-dev`
- Check logs: `gcloud app logs tail -s alice-dev`

## See Also

- [DEPLOYMENT_GUIDE.md](../DEPLOYMENT_GUIDE.md) - Complete deployment guide
- [QUICK_REFERENCE.md](../QUICK_REFERENCE.md) - Quick command reference
- [deploy_custom.sh](../deploy_custom.sh) - Automated deployment script
