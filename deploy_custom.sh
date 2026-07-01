#!/bin/bash
################################################################################
# Custom GCP Deployment Script for WildePod Django Application
# 
# This script creates a custom deployment with user-specified name prefix
# for all resources including:
# - Cloud SQL database instance
# - App Engine service
# - Cloud Storage buckets
# - Secret Manager secrets
# - Django settings and WSGI configuration
#
# Usage:
#   ./deploy_custom.sh <name-prefix> [options]
#
# Example:
#   ./deploy_custom.sh alice-dev --setup-db --full
#   ./deploy_custom.sh bob-test --use-existing-db --db-instance <YOUR-DB-INSTANCE> --full
#
# Options:
#   --setup-db          Create and configure Cloud SQL instance
#   --use-existing-db   Use existing Cloud SQL instance (prompts for name)
#   --migrate-db        Run database migrations only
#   --deploy-only       Deploy application without database operations
#   --full              Complete setup including database and deployment
#   --skip-tests        Skip running tests before deployment
#   --dry-run           Show what would be done without making changes
#   --project-id        GCP project ID (overrides $GCP_PROJECT_ID env var)
#   --region            GCP region (default: us-west2)
#   --db-instance       Existing database instance to use
################################################################################

set -e  # Exit on error
set -o pipefail  # Exit on pipe failure

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

print_usage() {
    cat << EOF
Usage: $0 <name-prefix> [options]

Arguments:
  <name-prefix>       Name prefix for all resources (e.g., 'alice-dev', 'bob-test')
                      Must contain only lowercase letters, numbers, and hyphens

Options:
  --setup-db          Create new Cloud SQL instance for this deployment
  --use-existing-db   Use existing Cloud SQL instance (specify with --db-instance)
  --db-instance NAME  Name of existing Cloud SQL instance to use
  --migrate-db        Run database migrations only
  --deploy-only       Deploy application without database operations
  --full              Complete setup including database and deployment
  --skip-tests        Skip running tests before deployment
  --dry-run           Show what would be done without making changes
  --project-id ID     GCP project ID (overrides $GCP_PROJECT_ID env var; required if not set)
  --region REGION     GCP region (default: us-west2)
  --db-tier TIER      Database tier (default: db-f1-micro)
  --help              Show this help message

Examples:
  # Set project ID via environment (recommended)
  export GCP_PROJECT_ID=<YOUR-PROJECT-ID>

  # Create new deployment with new database
  $0 alice-dev --setup-db --full

  # Create deployment using existing database instance
  $0 bob-test --use-existing-db --db-instance <YOUR-DB-INSTANCE> --full

  # Deploy only (assuming database exists)
  $0 charlie-staging --deploy-only

  # Dry run to see what would happen
  $0 dave-prod --dry-run --full
EOF
}

# Parse arguments
if [[ $# -eq 0 ]] || [[ "$1" == "--help" ]] || [[ "$1" == "-h" ]]; then
    print_usage
    exit 0
fi

NAME_PREFIX="$1"
shift

# Validate name prefix format
if [[ ! "$NAME_PREFIX" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]]; then
    log_error "Invalid name prefix: $NAME_PREFIX
Name must:
  - Start with a lowercase letter or number
  - Contain only lowercase letters, numbers, and hyphens
  - Be between 1 and 63 characters
  - Not start or end with a hyphen"
fi

# Default configuration
# GCP_PROJECT_ID must be set via environment variable or --project-id flag.
# Store the real value as: export GCP_PROJECT_ID=<your-project-id>
# (or set it in your shell profile / .deploy.config)
PROJECT_ID="${GCP_PROJECT_ID:-}"
REGION="${GCP_REGION:-us-west2}"
ZONE="us-west2-a"
DB_TIER="db-f1-micro"
DB_VERSION="POSTGRES_14"
EXISTING_DB_INSTANCE=""

# Parse options
SETUP_DB=false
USE_EXISTING_DB=false
MIGRATE_DB=false
DEPLOY_ONLY=false
FULL_DEPLOYMENT=false
SKIP_TESTS=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --setup-db)
            SETUP_DB=true
            shift
            ;;
        --use-existing-db)
            USE_EXISTING_DB=true
            SETUP_DB=true
            shift
            ;;
        --db-instance)
            EXISTING_DB_INSTANCE="$2"
            shift 2
            ;;
        --migrate-db)
            MIGRATE_DB=true
            shift
            ;;
        --deploy-only)
            DEPLOY_ONLY=true
            shift
            ;;
        --full)
            FULL_DEPLOYMENT=true
            shift
            ;;
        --skip-tests)
            SKIP_TESTS=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --project-id)
            PROJECT_ID="$2"
            shift 2
            ;;
        --region)
            REGION="$2"
            shift 2
            ;;
        --db-tier)
            DB_TIER="$2"
            shift 2
            ;;
        *)
            log_error "Unknown option: $1
Run with --help for usage information"
            ;;
    esac
done

# Set zone based on region if not explicitly set
if [[ "$REGION" == "us-west2" ]]; then
    ZONE="us-west2-a"
elif [[ "$REGION" == "us-central1" ]]; then
    ZONE="us-central1-a"
elif [[ "$REGION" == "us-east1" ]]; then
    ZONE="us-east1-b"
fi

# If using existing DB instance, require it to be specified
if [[ "$USE_EXISTING_DB" == true ]] && [[ -z "$EXISTING_DB_INSTANCE" ]]; then
    log_error "When using --use-existing-db, you must specify --db-instance NAME"
fi

# Require GCP project ID — never default to a hardcoded value
if [[ -z "$PROJECT_ID" ]]; then
    log_error "GCP project ID is required. Set it via:
  export GCP_PROJECT_ID=<your-project-id>
  or pass --project-id <your-project-id>"
fi

# Generate resource names based on prefix
SQL_INSTANCE_NAME="${EXISTING_DB_INSTANCE:-wildepod-${NAME_PREFIX}-db}"
DB_NAME="wildepod_${NAME_PREFIX//-/_}"  # Replace hyphens with underscores for DB name
DB_USER="wildepod_${NAME_PREFIX//-/_}_user"
SERVICE_NAME="$NAME_PREFIX"
APP_YAML="${NAME_PREFIX}.yaml"
SETTINGS_MODULE="config.settings.${NAME_PREFIX//-/_}"
WSGI_MODULE="config.wsgi.${NAME_PREFIX//-/_}"
BUCKET_NAME="${PROJECT_ID}-${NAME_PREFIX}-media"
SECRET_PREFIX="${NAME_PREFIX//-/_}"

# Set DB connection name
DB_CONNECTION_NAME="${PROJECT_ID}:${REGION}:${SQL_INSTANCE_NAME}"

log_info "================================"
log_info "Custom Deployment Configuration"
log_info "================================"
log_info "Name Prefix:        $NAME_PREFIX"
log_info "Project ID:         $PROJECT_ID"
log_info "Region:             $REGION"
log_info "Zone:               $ZONE"
log_info ""
log_info "Resource Names:"
log_info "  SQL Instance:     $SQL_INSTANCE_NAME"
log_info "  Database:         $DB_NAME"
log_info "  DB User:          $DB_USER"
log_info "  App Service:      $SERVICE_NAME"
log_info "  YAML File:        $APP_YAML"
log_info "  Settings Module:  $SETTINGS_MODULE"
log_info "  Storage Bucket:   $BUCKET_NAME"
log_info "================================"
log_info ""

if [ "$DRY_RUN" = true ]; then
    log_warning "DRY RUN MODE - No changes will be made"
fi

################################################################################
# Function: Check prerequisites
################################################################################
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    if ! command -v gcloud &> /dev/null; then
        log_error "gcloud CLI is not installed. Please install it from https://cloud.google.com/sdk/docs/install"
    fi
    
    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
        log_error "Not authenticated with gcloud. Run: gcloud auth login"
    fi
    
    if [ "$DRY_RUN" = false ]; then
        gcloud config set project "$PROJECT_ID" || log_error "Failed to set project"
    fi
    
    log_success "Prerequisites check completed"
}

################################################################################
# Function: Create configuration files
################################################################################
create_config_files() {
    log_info "Creating configuration files for $NAME_PREFIX..."
    
    local settings_file="config/settings/${NAME_PREFIX//-/_}.py"
    local wsgi_file="config/wsgi/${NAME_PREFIX//-/_}.py"
    
    # Create Django settings file
    if [ "$DRY_RUN" = false ]; then
        mkdir -p "config/settings"
        cat > "$settings_file" <<EOF
"""Django settings for ${NAME_PREFIX} environment"""

from .base import *  # noqa

# HOSTS CONFIG
# ------------------------------------------------------------------------------
ALLOWED_HOSTS = ["*"]

# DEBUG MODE
# ------------------------------------------------------------------------------
DEBUG = True

# https://docs.djangoproject.com/en/dev/ref/settings/#wsgi-application
WSGI_APPLICATION = "${WSGI_MODULE}.application"

# DATABASES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#databases
DATABASES = {"default": env.db("${NAME_PREFIX^^}_DATABASE_URL")}

# Enable Cloud SQL connection
if os.getenv("GAE_APPLICATION", None):
    DATABASES["default"]["HOST"] = f"/cloudsql/{DB_CONNECTION_NAME}"

# CACHES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#caches
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "",
    }
}

# SECURITY
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-ssl-redirect
SECURE_SSL_REDIRECT = False
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# https://docs.djangoproject.com/en/dev/ref/settings/#session-cookie-secure
SESSION_COOKIE_SECURE = False

# https://docs.djangoproject.com/en/dev/ref/settings/#csrf-cookie-secure
CSRF_COOKIE_SECURE = False

# STORAGES
# ------------------------------------------------------------------------------
# https://django-storages.readthedocs.io/en/latest/backends/gcloud.html
GS_BUCKET_NAME = "${BUCKET_NAME}"
GS_DEFAULT_ACL = "publicRead"
GS_FILE_OVERWRITE = False
GS_LOCATION = "media"

# Use GCS for media files
DEFAULT_FILE_STORAGE = "siteapps.my_utils.storages.MediaStorage"

# STATIC
# ------------------------------------------------------------------------------
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ADMIN
# ------------------------------------------------------------------------------
ADMIN_URL = "admin/"

# LOGGING
# ------------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s"
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        }
    },
    "root": {"level": "INFO", "handlers": ["console"]},
}
EOF
        log_success "Created settings file: $settings_file"
    else
        log_info "[DRY-RUN] Would create: $settings_file"
    fi
    
    # Create WSGI file
    if [ "$DRY_RUN" = false ]; then
        mkdir -p "config/wsgi"
        cat > "$wsgi_file" <<'EOF'
"""WSGI config for ${NAME_PREFIX} environment"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "${SETTINGS_MODULE}")

application = get_wsgi_application()
EOF
        # Replace placeholders
        sed -i "s/\${NAME_PREFIX}/${NAME_PREFIX}/g" "$wsgi_file"
        sed -i "s/\${SETTINGS_MODULE}/${SETTINGS_MODULE}/g" "$wsgi_file"
        log_success "Created WSGI file: $wsgi_file"
    else
        log_info "[DRY-RUN] Would create: $wsgi_file"
    fi
    
    # Create main Python entrypoint file
    local main_file="${NAME_PREFIX//-/_}.py"
    if [ "$DRY_RUN" = false ]; then
        cat > "$main_file" <<EOF
from ${WSGI_MODULE} import application

# App Engine looks for a module-level variable named 'app'
app = application
EOF
        log_success "Created entrypoint file: $main_file"
    else
        log_info "[DRY-RUN] Would create: $main_file"
    fi
    
    # Create App Engine YAML file
    if [ "$DRY_RUN" = false ]; then
        cat > "$APP_YAML" <<EOF
runtime: python310
instance_class: F1
service: ${SERVICE_NAME}
entrypoint: gunicorn -t 2400 -b :\$PORT ${NAME_PREFIX//-/_}:app

# Cloud SQL Configuration
beta_settings:
  cloud_sql_instances: ${DB_CONNECTION_NAME}

env_variables:
  DJANGO_SETTINGS_MODULE: ${SETTINGS_MODULE}
  CLOUD_SQL_CONNECTION_NAME: ${DB_CONNECTION_NAME}
  USE_CLOUD_SQL_AUTH_PROXY: "False"
  ${NAME_PREFIX^^}_DATABASE_URL: "postgres://${DB_USER}@/wildepod_${NAME_PREFIX//-/_}?host=/cloudsql/${DB_CONNECTION_NAME}"
EOF
        log_success "Created App Engine config: $APP_YAML"
    else
        log_info "[DRY-RUN] Would create: $APP_YAML"
    fi
}

################################################################################
# Function: Setup Cloud SQL Database
################################################################################
setup_database() {
    if [[ "$USE_EXISTING_DB" == true ]]; then
        log_info "Using existing Cloud SQL instance: $EXISTING_DB_INSTANCE"
        
        # Verify instance exists
        if ! gcloud sql instances describe "$EXISTING_DB_INSTANCE" --project="$PROJECT_ID" &>/dev/null; then
            log_error "Cloud SQL instance not found: $EXISTING_DB_INSTANCE"
        fi
        
        SQL_INSTANCE_NAME="$EXISTING_DB_INSTANCE"
        DB_CONNECTION_NAME="${PROJECT_ID}:${REGION}:${SQL_INSTANCE_NAME}"
        
        log_info "Creating database and user on existing instance..."
        
        # Generate password
        DB_PASSWORD=$(openssl rand -base64 32)
        
        if [ "$DRY_RUN" = false ]; then
            # Create database
            gcloud sql databases create "$DB_NAME" \
                --instance="$SQL_INSTANCE_NAME" \
                --project="$PROJECT_ID" 2>/dev/null || log_warning "Database may already exist"
            
            # Create user
            gcloud sql users create "$DB_USER" \
                --instance="$SQL_INSTANCE_NAME" \
                --password="$DB_PASSWORD" \
                --project="$PROJECT_ID" 2>/dev/null || log_warning "User may already exist"
            
            # Store password in Secret Manager
            echo -n "$DB_PASSWORD" | gcloud secrets create "${SECRET_PREFIX}_db_password" \
                --data-file=- \
                --replication-policy="automatic" \
                --project="$PROJECT_ID" 2>/dev/null || {
                echo -n "$DB_PASSWORD" | gcloud secrets versions add "${SECRET_PREFIX}_db_password" \
                    --data-file=- \
                    --project="$PROJECT_ID"
            }
            
            log_success "Database $DB_NAME created on instance $SQL_INSTANCE_NAME"
            log_success "User $DB_USER created"
            log_success "Password stored in Secret Manager: ${SECRET_PREFIX}_db_password"
        else
            log_info "[DRY-RUN] Would create database: $DB_NAME"
            log_info "[DRY-RUN] Would create user: $DB_USER"
            log_info "[DRY-RUN] Would store password in: ${SECRET_PREFIX}_db_password"
        fi
    else
        log_info "Creating new Cloud SQL instance: $SQL_INSTANCE_NAME"
        
        if [ "$DRY_RUN" = false ]; then
            # Check if instance already exists
            if gcloud sql instances describe "$SQL_INSTANCE_NAME" --project="$PROJECT_ID" &>/dev/null; then
                log_warning "Instance $SQL_INSTANCE_NAME already exists, skipping creation"
            else
                gcloud sql instances create "$SQL_INSTANCE_NAME" \
                    --database-version="$DB_VERSION" \
                    --tier="$DB_TIER" \
                    --region="$REGION" \
                    --project="$PROJECT_ID"
                log_success "Created Cloud SQL instance: $SQL_INSTANCE_NAME"
            fi
            
            # Create database and user
            DB_PASSWORD=$(openssl rand -base64 32)
            
            gcloud sql databases create "$DB_NAME" \
                --instance="$SQL_INSTANCE_NAME" \
                --project="$PROJECT_ID" 2>/dev/null || log_warning "Database may already exist"
            
            gcloud sql users create "$DB_USER" \
                --instance="$SQL_INSTANCE_NAME" \
                --password="$DB_PASSWORD" \
                --project="$PROJECT_ID" 2>/dev/null || log_warning "User may already exist"
            
            # Store password in Secret Manager
            echo -n "$DB_PASSWORD" | gcloud secrets create "${SECRET_PREFIX}_db_password" \
                --data-file=- \
                --replication-policy="automatic" \
                --project="$PROJECT_ID" 2>/dev/null || {
                echo -n "$DB_PASSWORD" | gcloud secrets versions add "${SECRET_PREFIX}_db_password" \
                    --data-file=- \
                    --project="$PROJECT_ID"
            }
            
            log_success "Database setup completed"
        else
            log_info "[DRY-RUN] Would create instance: $SQL_INSTANCE_NAME"
            log_info "[DRY-RUN] Would create database: $DB_NAME"
            log_info "[DRY-RUN] Would create user: $DB_USER"
        fi
    fi
}

################################################################################
# Function: Deploy to App Engine
################################################################################
deploy_app() {
    log_info "Deploying to App Engine..."
    
    if [ "$DRY_RUN" = false ]; then
        gcloud app deploy "$APP_YAML" \
            --project="$PROJECT_ID" \
            --quiet
        
        log_success "Deployment completed"
        log_info "Application URL: https://${SERVICE_NAME}-dot-${PROJECT_ID}.appspot.com"
    else
        log_info "[DRY-RUN] Would deploy: $APP_YAML"
        log_info "[DRY-RUN] Target URL: https://${SERVICE_NAME}-dot-${PROJECT_ID}.appspot.com"
    fi
}

################################################################################
# Main execution
################################################################################

check_prerequisites

# Create configuration files
create_config_files

# Setup database if requested
if [[ "$SETUP_DB" == true ]] || [[ "$FULL_DEPLOYMENT" == true ]]; then
    setup_database
fi

# Deploy application if requested
if [[ "$DEPLOY_ONLY" == true ]] || [[ "$FULL_DEPLOYMENT" == true ]]; then
    deploy_app
fi

log_success "All operations completed successfully!"
log_info ""
log_info "Next steps:"
log_info "1. Run migrations: ./post_deploy_setup.sh $NAME_PREFIX"
log_info "2. Access your app: https://${SERVICE_NAME}-dot-${PROJECT_ID}.appspot.com"
log_info "3. View logs: gcloud app logs tail -s $SERVICE_NAME"
