# WildePod GCP Deployment Guide

Complete guide for deploying WildePod Django application to Google Cloud Platform.

## Quick Start

### Custom Deployment (Recommended for Development)
```bash
# Create your personal environment
./deploy_custom.sh <your-name>-dev --use-existing-db --db-instance <YOUR-DB-INSTANCE> --full
./post_deploy_setup.sh <your-name>-dev
```

### Standard Environments
```bash
# Deploy to predefined environment (staging/prod/bhutan)
./deploy_gcp.sh staging --full
```

## Table of Contents
- [Prerequisites](#prerequisites)
- [Deployment Methods](#deployment-methods)
- [Custom Deployments](#custom-deployments)
- [Standard Deployments](#standard-deployments)
- [Database Options](#database-options)
- [Post-Deployment Setup](#post-deployment-setup)
- [Dry-Run Mode](#dry-run-mode)
- [GitHub Actions CI/CD](#github-actions-cicd)
- [Monitoring and Maintenance](#monitoring-and-maintenance)
- [Troubleshooting](#troubleshooting)

## Prerequisites

### Required Tools
1. **Google Cloud SDK (gcloud)**
   ```bash
   curl https://sdk.cloud.google.com | bash
   exec -l $SHELL
   gcloud init
   ```

2. **Cloud SQL Proxy v2** (for local database access)
   ```bash
   curl -o cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.14.2/cloud-sql-proxy.linux.amd64
   chmod +x cloud-sql-proxy
   sudo mv cloud-sql-proxy /usr/local/bin/
   ```

3. **Python 3.10+** with uv
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   uv sync
   ```

### GCP Authentication
```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project <YOUR-PROJECT-ID>
```

### Required APIs
```bash
gcloud services enable sqladmin.googleapis.com
gcloud services enable appengine.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable secretmanager.googleapis.com
```

## Deployment Methods

WildePod supports two deployment approaches:

### Custom Deployments
**User-specified name prefixes for all resources**
- Perfect for: Personal dev, feature testing, experimentation
- Cost: < $1/month (with shared database)
- Setup time: 5 minutes
- Script: `deploy_custom.sh`

### Standard Deployments
**Predefined environments (staging, prod, bhutan)**
- Perfect for: Production, official staging
- Cost: $25-200/month (dedicated resources)
- Setup time: 15-30 minutes
- Script: `deploy_gcp.sh`

## Custom Deployments

### Creating Custom Environment

**With Existing Database (Recommended)**
```bash
./deploy_custom.sh alice-dev --use-existing-db --db-instance <YOUR-DB-INSTANCE> --full
./post_deploy_setup.sh alice-dev
```

**With New Database Instance**
```bash
./deploy_custom.sh alice-dev --setup-db --full --db-tier db-f1-micro
./post_deploy_setup.sh alice-dev
```

**Deploy Only (Database Exists)**
```bash
./deploy_custom.sh alice-dev --deploy-only
```

### Name Requirements
- Lowercase letters, numbers, and hyphens only
- 1-63 characters
- Start with letter or number
- No underscores or uppercase

**Valid**: `alice-dev`, `team-staging`, `experiment-123`
**Invalid**: `Alice-Dev`, `my_env`, `-test`, `dev-`

### Resource Naming
For prefix `alice-dev`:
- Service: `alice-dev`
- Database: `wildepod_alice_dev`
- DB User: `wildepod_alice_dev_user`
- Settings: `config.settings.alice_dev`
- Bucket: `<YOUR-PROJECT-ID>-alice-dev-media`
- URL: `https://alice-dev-dot-<YOUR-PROJECT-ID>.appspot.com`

### Custom Deployment Options
```bash
--use-existing-db          Use existing Cloud SQL instance
--db-instance NAME         Existing instance name (e.g., <YOUR-DB-INSTANCE>)
--setup-db                 Create new Cloud SQL instance
--deploy-only              Deploy app only (skip database)
--full                     Complete deployment (database + app)
--dry-run                  Show what would happen without changes
--project-id ID            GCP project (required: set via $GCP_PROJECT_ID or --project-id flag)
--region REGION            GCP region (default: us-west2)
--db-tier TIER             Database tier (default: db-f1-micro)
```

### Managing Custom Deployments

**View All Deployments**
```bash
gcloud app services list
gcloud sql databases list --instance=<YOUR-DB-INSTANCE>
```

**Update Deployment**
```bash
# Make code changes, then:
gcloud app deploy alice-dev.yaml
```

**Delete Deployment**
```bash
NAME="alice-dev"
gcloud app services delete ${NAME}
gcloud sql databases delete wildepod_${NAME//-/_} --instance=<YOUR-DB-INSTANCE>
gsutil -m rm -r gs://<YOUR-PROJECT-ID>-${NAME}-media/
gcloud secrets delete ${NAME//-/_}_db_password
gcloud secrets delete ${NAME//-/_}_django_secret
rm -f ${NAME}.yaml ${NAME//-/_}.py config/settings/${NAME//-/_}.py config/wsgi/${NAME//-/_}.py
```

## Standard Deployments

### Available Environments
- **staging** - Team staging environment
- **prod** - Production environment
- **bhutan** - Bhutan-specific deployment

### Deployment Commands

**Full Deployment**
```bash
./deploy_gcp.sh staging --full
```

**With Existing Database**
```bash
./deploy_gcp.sh staging --use-existing-db <YOUR-DB-INSTANCE>
```

**Deploy Only**
```bash
./deploy_gcp.sh staging --deploy-only
```

**Migrations Only**
```bash
./deploy_gcp.sh staging --migrate-db
```

### Standard Deployment Options
```bash
--setup-db                 Create and configure Cloud SQL instance
--use-existing-db NAME     Use existing Cloud SQL instance
--migrate-db               Run database migrations only
--deploy-only              Deploy without database operations
--full                     Complete setup (database + deployment)
--skip-tests               Skip running tests before deployment
--dry-run                  Show what would be done without changes
```

## Database Options

### Using Existing Database Instance

**Benefits:**
- Saves costs (no new instance charges)
- Faster setup
- Shared resources for development
- Best for: Development, testing, multiple dev environments

**Usage:**
```bash
# Custom deployment
./deploy_custom.sh myname-dev --use-existing-db --db-instance <YOUR-DB-INSTANCE> --full

# Standard deployment
./deploy_gcp.sh staging --use-existing-db <YOUR-DB-INSTANCE>
```

**How it works:**
1. Verifies instance exists in your project
2. Creates new database on existing instance
3. Creates database user with secure password
4. Stores credentials in Secret Manager
5. Configures app to connect to this database

### Creating New Database Instance

**Benefits:**
- Complete isolation
- Dedicated resources
- Independent scaling
- Separate backups
- Best for: Production, high-performance needs

**Database Tiers:**
```bash
db-f1-micro           # Shared CPU, 0.6GB RAM, ~$7/month
db-g1-small           # Shared CPU, 1.7GB RAM, ~$35/month
db-custom-1-3840      # 1 vCPU, 3.75GB RAM, ~$25/month
db-custom-2-7680      # 2 vCPU, 7.5GB RAM, ~$120/month
db-custom-4-15360     # 4 vCPU, 15GB RAM, ~$240/month
```

**Usage:**
```bash
# Custom deployment with new instance
./deploy_custom.sh myenv --setup-db --full --db-tier db-custom-2-7680

# Standard deployment with new instance
./deploy_gcp.sh prod --setup-db --full
```

### Cost Comparison
| Configuration | Monthly Cost | Best For |
|--------------|--------------|----------|
| Shared DB (existing) | < $1 | Personal dev, testing |
| New DB (f1-micro) | ~$7 | Small projects |
| New DB (custom-1-3840) | ~$25 | Team staging |
| New DB (custom-2-7680) | ~$120 | Production |

## Post-Deployment Setup

After deploying, complete the setup:

```bash
./post_deploy_setup.sh <environment-name>
```

**This script:**
1. Connects to Cloud SQL via proxy
2. Runs Django database migrations
3. Creates/configures Cloud Storage bucket
4. Collects Django static files
5. Creates Django superuser account
6. Generates and stores Django secret key
7. Tests the deployment

**Default superuser credentials:**
- Email: `<environment>@example.com`
- Password: `letmein`

**Change password immediately:**
```bash
python manage.py changepassword <environment>@example.com
```

## Dry-Run Mode

Test deployments without making changes:

```bash
# Custom deployment dry-run
./deploy_custom.sh test-env --use-existing-db --db-instance <YOUR-DB-INSTANCE> --full --dry-run

# Standard deployment dry-run
./deploy_gcp.sh staging --full --dry-run
```

**Dry-run shows:**
- Commands that would be executed
- Resources that would be created
- Configuration changes
- Estimated costs

**Use dry-run when:**
- Testing new deployment configurations
- Verifying resource names
- Training new team members
- Documenting deployment process

## GitHub Actions CI/CD

### Automatic Workflow Generation

The deployment script creates GitHub Actions workflows:

```bash
# Deploys and creates .github/workflows/deploy-{env}.yml
./deploy_gcp.sh staging --full
```

### Manual Workflow Setup

1. **Create Service Account:**
```bash
gcloud iam service-accounts create github-deployer \
    --display-name="GitHub Actions Deployer"

gcloud projects add-iam-policy-binding <YOUR-PROJECT-ID> \
    --member="serviceAccount:github-deployer@<YOUR-PROJECT-ID>.iam.gserviceaccount.com" \
    --role="roles/appengine.deployer"
```

2. **Create and Download Key:**
```bash
gcloud iam service-accounts keys create key.json \
    --iam-account=github-deployer@<YOUR-PROJECT-ID>.iam.gserviceaccount.com
```

3. **Add to GitHub Secrets:**
- Go to repository → Settings → Secrets
- Add secret: `GCP_SA_KEY` = contents of `key.json`

4. **Trigger Deployment:**
- Push to specific branch
- Manual workflow dispatch
- Pull request to protected branch

## Monitoring and Maintenance

### View Logs
```bash
# Real-time logs
gcloud app logs tail -s <service-name>

# Recent logs
gcloud app logs read --service=<service-name> --limit=100

# Filter by severity
gcloud app logs read --service=<service-name> --severity=ERROR
```

### Check Application Status
```bash
# Service status
gcloud app services describe <service-name>

# Version information
gcloud app versions list --service=<service-name>

# Instance status
gcloud app instances list --service=<service-name>
```

### Database Management
```bash
# Connect to database
cloud-sql-proxy --port 5433 <YOUR-PROJECT-ID>:us-west2:<YOUR-DB-INSTANCE>

# In another terminal
psql "host=127.0.0.1 port=5433 dbname=wildepod_<env> user=wildepod_<env>_user"

# Create backup
gcloud sql backups create --instance=<YOUR-DB-INSTANCE>

# List backups
gcloud sql backups list --instance=<YOUR-DB-INSTANCE>

# Restore from backup
gcloud sql backups restore BACKUP_ID --backup-instance=<YOUR-DB-INSTANCE>
```

### Update Deployment
```bash
# Update code and redeploy
git pull
gcloud app deploy <environment>.yaml

# Or use deployment script
./deploy_gcp.sh staging --deploy-only
```

### Scale Resources
```bash
# Update App Engine YAML
# Edit <environment>.yaml:
automatic_scaling:
  max_instances: 10
  min_instances: 2

# Redeploy
gcloud app deploy <environment>.yaml

# Scale database (requires downtime)
gcloud sql instances patch <YOUR-DB-INSTANCE> --tier=db-custom-4-15360
```

## Troubleshooting

### Common Issues

**Issue: Authentication Error**
```bash
# Re-authenticate
gcloud auth login
gcloud auth application-default login
```

**Issue: Database Connection Failed**
```bash
# Check instance exists and is running
gcloud sql instances describe <YOUR-DB-INSTANCE>

# Verify region matches
gcloud sql instances describe <YOUR-DB-INSTANCE> --format="value(region)"

# Test connection
cloud-sql-proxy --port 5433 <YOUR-PROJECT-ID>:us-west2:<YOUR-DB-INSTANCE>
psql "host=127.0.0.1 port=5433 dbname=postgres user=postgres"
```

**Issue: 502 Bad Gateway**
```bash
# Check application logs
gcloud app logs read --service=<service> --limit=50

# Common causes:
# 1. Django settings module not found
# 2. Database connection misconfigured
# 3. Import errors (check all imports use siteapps.* prefix)
# 4. Missing environment variables
```

**Issue: Static Files Not Loading**
```bash
# Recollect static files
export DJANGO_SETTINGS_MODULE=config.settings.<env>
python manage.py collectstatic --noinput

# Or rerun post-deployment
./post_deploy_setup.sh <environment>
```

**Issue: Migration Errors**
```bash
# Check current migration status
python manage.py showmigrations --settings=config.settings.<env>

# Fake migrations if needed (careful!)
python manage.py migrate --fake <app> <migration> --settings=config.settings.<env>

# Or start fresh (WARNING: destroys data!)
# Drop and recreate database
gcloud sql databases delete wildepod_<env> --instance=<YOUR-DB-INSTANCE>
gcloud sql databases create wildepod_<env> --instance=<YOUR-DB-INSTANCE>
./post_deploy_setup.sh <environment>
```

**Issue: Import Module Errors**
```bash
# All imports must use full siteapps prefix
# ✅ Correct:
from siteapps.users.models import User
from siteapps.images.models import Image

# ❌ Wrong:
from users.models import User
from images.models import Image

# Check app configs have full names
# In siteapps/users/apps.py:
class UsersConfig(AppConfig):
    name = "siteapps.users"  # ✅ Correct
    # name = "users"  # ❌ Wrong
```

### Getting Help
1. Check logs: `gcloud app logs tail -s <service>`
2. Verify resources in Cloud Console
3. Test locally with Cloud SQL Proxy
4. Check this guide's troubleshooting section
5. Review error messages carefully

### Useful Commands
```bash
# List all services
gcloud app services list

# List all databases
gcloud sql databases list --instance=<YOUR-DB-INSTANCE>

# List all secrets
gcloud secrets list

# List all storage buckets
gsutil ls

# Check project configuration
gcloud config list

# View project info
gcloud projects describe <YOUR-PROJECT-ID>
```

## Best Practices

1. **Use descriptive names**: `alice-dev`, `sprint-5`, not `test1`, `temp`
2. **Always dry-run first**: Test with `--dry-run` before actual deployment
3. **Share databases for dev**: Use `--use-existing-db` to save costs
4. **Clean up regularly**: Delete unused test environments
5. **Document environments**: Keep track of active deployments
6. **Separate prod from dev**: Use dedicated instances for production
7. **Version control configs**: Commit generated configs for important environments
8. **Monitor costs**: Set up billing alerts in GCP Console
9. **Regular backups**: Enable automated backups for production databases
10. **Security reviews**: Rotate passwords, review IAM permissions quarterly

## Quick Reference

### Deploy Commands
```bash
# Custom deployment (shared DB)
./deploy_custom.sh <name> --use-existing-db --db-instance <YOUR-DB-INSTANCE> --full

# Custom deployment (new DB)
./deploy_custom.sh <name> --setup-db --full

# Standard deployment
./deploy_gcp.sh <env> --full

# Post-deployment setup
./post_deploy_setup.sh <name>
```

### Common Operations
```bash
# View logs
gcloud app logs tail -s <service>

# Update app
gcloud app deploy <environment>.yaml

# Access app
gcloud app browse -s <service>

# Connect to database
cloud-sql-proxy --port 5433 <YOUR-PROJECT-ID>:us-west2:<YOUR-DB-INSTANCE>
```

### Resource Locations
- **App Engine**: https://console.cloud.google.com/appengine
- **Cloud SQL**: https://console.cloud.google.com/sql
- **Storage**: https://console.cloud.google.com/storage
- **Secrets**: https://console.cloud.google.com/security/secret-manager
- **Logs**: https://console.cloud.google.com/logs

## See Also
- [Quick Reference](QUICK_REFERENCE.md) - Command cheat sheet
- [README.md](README.md) - Main project documentation
- [GCP Documentation](https://cloud.google.com/appengine/docs)
