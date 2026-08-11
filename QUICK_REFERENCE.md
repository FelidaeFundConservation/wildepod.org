# Quick Deployment Reference

## Custom Deployments

### Create New Environment
```bash
# Using existing database (recommended)
./deploy_custom.sh <your-name-env> --use-existing-db --db-instance <YOUR-DB-INSTANCE> --full
./post_deploy_setup.sh <your-name-env>

# With new database
./deploy_custom.sh <your-name-env> --setup-db --full
./post_deploy_setup.sh <your-name-env>
```

### Resource Names (example: alice-dev)
| Resource | Name |
|----------|------|
| Service | `alice-dev` |
| Database | `wildepod_alice_dev` |
| DB User | `wildepod_alice_dev_user` |
| Settings | `config.settings.alice_dev` |
| Bucket | `<YOUR-PROJECT-ID>-alice-dev-media` |
| URL | `https://alice-dev-dot-<YOUR-PROJECT-ID>.appspot.com` |

### Name Rules
- ✅ Lowercase letters, numbers, hyphens only
- ✅ 1-63 characters
- ✅ Start with letter or number
- ❌ No underscores, uppercase, or spaces

## Standard Deployments

### Deploy to Standard Environments
```bash
# Staging
./deploy_gcp.sh staging --full

# Production
./deploy_gcp.sh prod --full

# Bhutan
./deploy_gcp.sh bhutan --full
```

## Common Commands

### Deployment
```bash
# Deploy code changes
gcloud app deploy <environment>.yaml

# View logs
gcloud app logs tail -s <service-name>

# Access app
gcloud app browse -s <service-name>

# Run migrations
python manage.py migrate --settings=config.settings.<env_name>

# Create superuser
python manage.py createsuperuser --settings=config.settings.<env_name>
```

### Database
```bash
# Connect to database
cloud-sql-proxy --port 5433 <YOUR-PROJECT-ID>:us-west2:<YOUR-DB-INSTANCE>

# In another terminal
psql "host=127.0.0.1 port=5433 dbname=wildepod_<env> user=wildepod_<env>_user"

# List databases
gcloud sql databases list --instance=<YOUR-DB-INSTANCE>

# Create backup
gcloud sql backups create --instance=<YOUR-DB-INSTANCE>

# List backups
gcloud sql backups list --instance=<YOUR-DB-INSTANCE>
```

### Monitoring
```bash
# List all services
gcloud app services list

# Service status
gcloud app services describe <service-name>

# Version information
gcloud app versions list --service=<service-name>

# Recent logs with errors
gcloud app logs read --service=<service-name> --severity=ERROR --limit=50
```

### Cleanup
```bash
# Delete service
gcloud app services delete <service-name>

# Delete database
gcloud sql databases delete wildepod_<env> --instance=<YOUR-DB-INSTANCE>

# Delete user
gcloud sql users delete wildepod_<env>_user --instance=<YOUR-DB-INSTANCE>

# Delete storage bucket
gsutil -m rm -r gs://<YOUR-PROJECT-ID>-<env>-media/

# Delete secrets
gcloud secrets delete <env>_db_password
gcloud secrets delete <env>_django_secret

# Delete local config files
rm -f <env>.yaml <env>.py config/settings/<env>.py config/wsgi/<env>.py
```

## Environment Variables

### For Local Development
```bash
export DJANGO_SETTINGS_MODULE=config.settings.<env>
export <ENV>_DATABASE_URL="postgres://<user>:<password>@127.0.0.1:5433/<dbname>"
export GOOGLE_CLOUD_PROJECT=<YOUR-PROJECT-ID>
```

### Example (alice-dev)
```bash
export DJANGO_SETTINGS_MODULE=config.settings.alice_dev
export ALICE_DEV_DATABASE_URL="postgres://wildepod_alice_dev_user:password@127.0.0.1:5433/wildepod_alice_dev"
export GOOGLE_CLOUD_PROJECT=<YOUR-PROJECT-ID>
```

## Cost Estimates

| Deployment Type | Monthly Cost | Best For |
|----------------|--------------|----------|
| Custom (shared DB) | < $1 | Personal dev, testing |
| Custom (new DB f1-micro) | ~$7 | Small projects |
| Custom (new DB custom-1-3840) | ~$25 | Team staging |
| Standard staging | ~$25 | Official staging |
| Standard prod | $50-200+ | Production |

## Troubleshooting

### Authentication Error
```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project <YOUR-PROJECT-ID>
```

### Database Connection Error
```bash
# Check instance exists
gcloud sql instances describe <YOUR-DB-INSTANCE>

# Test connection
cloud-sql-proxy --port 5433 <YOUR-PROJECT-ID>:us-west2:<YOUR-DB-INSTANCE>
psql "host=127.0.0.1 port=5433 dbname=postgres user=postgres"
```

### 502 Bad Gateway
```bash
# Check logs for errors
gcloud app logs read --service=<service> --limit=50

# Common causes:
# - Django settings module not found
# - Database connection misconfigured
# - Import errors (must use siteapps.* prefix)
# - Missing environment variables
```

### Import Errors
```bash
# ✅ Correct
from siteapps.users.models import User
from siteapps.images.models import Image

# ❌ Wrong
from users.models import User
from images.models import Image
```

## Quick Setup Checklist

- [ ] Install Google Cloud SDK
- [ ] Authenticate: `gcloud auth login`
- [ ] Install Cloud SQL Proxy v2
- [ ] Install Python 3.10+ with uv
- [ ] Run `uv sync` to install dependencies
- [ ] Choose deployment method (custom vs standard)
- [ ] Run deployment script with `--dry-run` first
- [ ] Execute actual deployment
- [ ] Run `post_deploy_setup.sh`
- [ ] Test application access
- [ ] Change default superuser password

## Useful Links

- Full Documentation: [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)
- Main README: [README.md](README.md)
- GCP Console: https://console.cloud.google.com
- App Engine: https://console.cloud.google.com/appengine
- Cloud SQL: https://console.cloud.google.com/sql
- Storage: https://console.cloud.google.com/storage
- Secrets: https://console.cloud.google.com/security/secret-manager
