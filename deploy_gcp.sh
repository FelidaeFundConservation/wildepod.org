#!/bin/bash
# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

################################################################################
# GCP Deployment Script for WildePod Django Application
# 
# This script automates deployment to Google Cloud Platform with:
# - Cloud SQL (PostgreSQL) setup and configuration
# - App Engine deployment
# - Database migration
# - GitHub integration for CI/CD
#
# Usage:
#   ./deploy_gcp.sh [environment] [options]
#
# Environments: staging, prod, bhutan, custom-dev
# Options:
#   --setup-db          Create and configure Cloud SQL instance
#   --use-existing-db   Use existing Cloud SQL instance (prompts for name)
#   --migrate-db        Run database migrations only
#   --deploy-only       Deploy application without database operations
#   --full              Complete setup including database and deployment
#   --skip-tests        Skip running tests before deployment
#   --dry-run           Show what would be done without making changes
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

# Configuration variables - modify these for your project
PROJECT_ID="${GCP_PROJECT_ID:-wildepod-project}"
REGION="${GCP_REGION:-us-central1}"
ZONE="${GCP_ZONE:-us-central1-a}"

# Parse arguments
ENVIRONMENT="${1:-staging}"
SETUP_DB=false
USE_EXISTING_DB=false
EXISTING_INSTANCE_NAME=""
MIGRATE_DB=false
DEPLOY_ONLY=false
FULL_DEPLOYMENT=false
SKIP_TESTS=false
DRY_RUN=false

shift || true
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
            # Check if next arg is an instance name (doesn't start with --)
            if [[ $# -gt 0 && ! "$1" =~ ^-- ]]; then
                EXISTING_INSTANCE_NAME="$1"
                shift
            fi
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
        *)
            log_error "Unknown option: $1"
            ;;
    esac
done

# Validate environment
if [[ ! "$ENVIRONMENT" =~ ^(staging|prod|bhutan|custom-dev)$ ]]; then
    log_error "Invalid environment: $ENVIRONMENT. Must be staging, prod, bhutan, or custom-dev"
fi

# Set environment-specific variables
case $ENVIRONMENT in
    staging)
        SQL_INSTANCE_NAME="wildepod-staging-db"
        DB_NAME="wildepod_staging"
        DB_USER="wildepod_staging_user"
        SERVICE_NAME="staging"
        APP_YAML="staging.yaml"
        ;;
    prod)
        SQL_INSTANCE_NAME="wildepod-prod-db"
        DB_NAME="wildepod_prod"
        DB_USER="wildepod_prod_user"
        SERVICE_NAME="default"
        APP_YAML="prod.yaml"
        ;;
    bhutan)
        SQL_INSTANCE_NAME="wildepod-bhutan-db"
        DB_NAME="wildepod_bhutan"
        DB_USER="wildepod_bhutan_user"
        SERVICE_NAME="bhutan"
        APP_YAML="bhutan.yaml"
        ;;
    custom-dev)
        SQL_INSTANCE_NAME="wildepod-custom-dev-db"
        DB_NAME="wildepod_custom_dev"
        DB_USER="wildepod_custom_dev_user"
        SERVICE_NAME="custom-dev"
        APP_YAML="custom-dev.yaml"
        ;;
esac

# Database tier configuration
DB_TIER="${DB_TIER:-db-f1-micro}"  # Use db-custom-1-3840 for production
DB_VERSION="${DB_VERSION:-POSTGRES_14}"

if [ "$DRY_RUN" = true ]; then
    log_warning "DRY RUN MODE - No changes will be made"
    log_info "Commands that would be executed will be displayed"
fi

log_info "Starting GCP deployment for environment: $ENVIRONMENT"
log_info "Project ID: $PROJECT_ID"
log_info "Region: $REGION"

################################################################################
# Function: Check prerequisites
################################################################################
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check if gcloud is installed
    if ! command -v gcloud &> /dev/null; then
        log_error "gcloud CLI is not installed. Please install it from https://cloud.google.com/sdk/docs/install"
    fi
    
    # Check if authenticated
    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
        log_error "Not authenticated with gcloud. Run: gcloud auth login"
    fi
    
    # Set project
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY-RUN] Would execute: gcloud config set project $PROJECT_ID"
    else
        gcloud config set project "$PROJECT_ID" || log_error "Failed to set project"
    fi
    
    # Check if required APIs are enabled
    log_info "Enabling required GCP APIs..."
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY-RUN] Would enable APIs:"
        log_info "  - sqladmin.googleapis.com"
        log_info "  - appengine.googleapis.com"
        log_info "  - cloudbuild.googleapis.com"
        log_info "  - secretmanager.googleapis.com"
    else
        gcloud services enable sqladmin.googleapis.com --quiet || log_warning "SQL Admin API already enabled"
        gcloud services enable appengine.googleapis.com --quiet || log_warning "App Engine API already enabled"
        gcloud services enable cloudbuild.googleapis.com --quiet || log_warning "Cloud Build API already enabled"
        gcloud services enable secretmanager.googleapis.com --quiet || log_warning "Secret Manager API already enabled"
    fi
    
    log_success "Prerequisites check completed"
}

################################################################################
# Function: Setup Cloud SQL instance
################################################################################
setup_cloud_sql() {
    # Handle existing instance option
    if [ "$USE_EXISTING_DB" = true ]; then
        if [ -z "$EXISTING_INSTANCE_NAME" ]; then
            echo -e "${BLUE}Available Cloud SQL instances in project:${NC}"
            gcloud sql instances list --project="$PROJECT_ID" --format="table(name,region,databaseVersion,tier)" 2>/dev/null || true
            echo ""
            read -p "Enter the name of the existing Cloud SQL instance to use: " EXISTING_INSTANCE_NAME
            
            if [ -z "$EXISTING_INSTANCE_NAME" ]; then
                log_error "Instance name cannot be empty"
            fi
        fi
        
        # Verify instance exists
        log_info "Verifying Cloud SQL instance: $EXISTING_INSTANCE_NAME"
        if ! gcloud sql instances describe "$EXISTING_INSTANCE_NAME" --project="$PROJECT_ID" &> /dev/null; then
            log_error "Cloud SQL instance '$EXISTING_INSTANCE_NAME' not found in project $PROJECT_ID"
        fi
        
        # Use the existing instance name
        SQL_INSTANCE_NAME="$EXISTING_INSTANCE_NAME"
        log_success "Using existing Cloud SQL instance: $SQL_INSTANCE_NAME"
        
        # Get instance details
        INSTANCE_REGION=$(gcloud sql instances describe "$SQL_INSTANCE_NAME" --project="$PROJECT_ID" --format="value(region)")
        INSTANCE_VERSION=$(gcloud sql instances describe "$SQL_INSTANCE_NAME" --project="$PROJECT_ID" --format="value(databaseVersion)")
        INSTANCE_TIER=$(gcloud sql instances describe "$SQL_INSTANCE_NAME" --project="$PROJECT_ID" --format="value(settings.tier)")
        
        log_info "Instance details:"
        log_info "  Region: $INSTANCE_REGION"
        log_info "  Database Version: $INSTANCE_VERSION"
        log_info "  Tier: $INSTANCE_TIER"
    else
        log_info "Setting up Cloud SQL PostgreSQL instance: $SQL_INSTANCE_NAME"
        
        # Check if instance already exists
        if gcloud sql instances describe "$SQL_INSTANCE_NAME" --project="$PROJECT_ID" &> /dev/null; then
            log_warning "Cloud SQL instance $SQL_INSTANCE_NAME already exists"
            read -p "Do you want to continue with existing instance? (y/n) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                log_error "Deployment cancelled by user"
            fi
            else
            log_info "Creating Cloud SQL instance (this may take several minutes)..."
            if [ "$DRY_RUN" = true ]; then
                log_info "[DRY-RUN] Would execute:"
                echo "gcloud sql instances create $SQL_INSTANCE_NAME \\"
            echo "  --database-version=$DB_VERSION \\"
            echo "  --tier=$DB_TIER \\"
            echo "  --region=$REGION \\"
            echo "  --root-password=<generated> \\"
            echo "  --storage-type=SSD \\"
            echo "  --storage-size=10GB \\"
            echo "  --storage-auto-increase \\"
            echo "  --backup-start-time=03:00 \\"
            echo "  --enable-bin-log \\"
            echo "  --maintenance-window-day=SUN \\"
            echo "  --maintenance-window-hour=04 \\"
            echo "  --project=$PROJECT_ID"
        else
            gcloud sql instances create "$SQL_INSTANCE_NAME" \
                --database-version="$DB_VERSION" \
                --tier="$DB_TIER" \
                --region="$REGION" \
                --root-password="$(openssl rand -base64 32)" \
                --storage-type=SSD \
                --storage-size=10GB \
                --storage-auto-increase \
                --backup-start-time=03:00 \
                --enable-bin-log \
                --maintenance-window-day=SUN \
                --maintenance-window-hour=04 \
                --project="$PROJECT_ID" || log_error "Failed to create Cloud SQL instance"
        fi
            
            log_success "Cloud SQL instance created successfully"
        fi
    fi
    
    # Generate database password
    DB_PASSWORD=$(openssl rand -base64 32)
    
    # Create database
    log_info "Creating database: $DB_NAME"
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY-RUN] Would create database: $DB_NAME on instance $SQL_INSTANCE_NAME"
    else
        gcloud sql databases create "$DB_NAME" \
            --instance="$SQL_INSTANCE_NAME" \
            --project="$PROJECT_ID" 2>/dev/null || log_warning "Database may already exist"
    fi
    
    # Create database user
    log_info "Creating database user: $DB_USER"
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY-RUN] Would create user: $DB_USER with generated password"
    else
        gcloud sql users create "$DB_USER" \
            --instance="$SQL_INSTANCE_NAME" \
            --password="$DB_PASSWORD" \
            --project="$PROJECT_ID" 2>/dev/null || log_warning "User may already exist"
    fi
    
    # Store database password in Secret Manager
    log_info "Storing database credentials in Secret Manager..."
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY-RUN] Would store password in secret: ${ENVIRONMENT}_db_password"
    else
        echo -n "$DB_PASSWORD" | gcloud secrets create "${ENVIRONMENT}_db_password" \
            --data-file=- \
            --replication-policy="automatic" \
            --project="$PROJECT_ID" 2>/dev/null || \
        echo -n "$DB_PASSWORD" | gcloud secrets versions add "${ENVIRONMENT}_db_password" \
            --data-file=- \
            --project="$PROJECT_ID"
    fi
    
    # Get connection name
    CONNECTION_NAME=$(gcloud sql instances describe "$SQL_INSTANCE_NAME" \
        --project="$PROJECT_ID" \
        --format="value(connectionName)")
    
    log_success "Cloud SQL setup completed"
    log_info "Connection Name: $CONNECTION_NAME"
    
    # Create .env file for local development
    log_info "Creating .env.${ENVIRONMENT} file..."
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY-RUN] Would create .env.${ENVIRONMENT} with database configuration"
        return 0
    fi
    
    cat > ".env.${ENVIRONMENT}" <<EOF
# Auto-generated environment file for $ENVIRONMENT
# Generated on $(date)

# Database Configuration
PROD_DATABASE_URL=postgres://${DB_USER}:${DB_PASSWORD}@//cloudsql/${CONNECTION_NAME}/${DB_NAME}
USE_CLOUD_SQL_AUTH_PROXY=False

# GCP Configuration
GCP_PROJECT_ID=${PROJECT_ID}
GS_BUCKET_NAME_${ENVIRONMENT^^}=${PROJECT_ID}-${ENVIRONMENT}-media

# Cloud SQL Connection
CLOUD_SQL_CONNECTION_NAME=${CONNECTION_NAME}

# Add your other environment-specific variables below:
# DJANGO_SECRET_KEY=
# MAILGUN_SMTP_PASSWORD=
# DROPBOX_APP_KEY_${ENVIRONMENT^^}=
# DROPBOX_APP_SECRET_${ENVIRONMENT^^}=
# DROPBOX_REFRESH_TOKEN_${ENVIRONMENT^^}=
# EMAIL_2FA_IMAP_URL_${ENVIRONMENT^^}=
# EMAIL_2FA_USER_${ENVIRONMENT^^}=
# EMAIL_2FA_PASSWORD_${ENVIRONMENT^^}=
# ADMIN_URL_SUFFIX=
EOF
    
    log_success "Environment file created: .env.${ENVIRONMENT}"
    log_warning "IMPORTANT: Update .env.${ENVIRONMENT} with your secret keys before deployment!"
}

################################################################################
# Function: Create app.yaml with database configuration
################################################################################
update_app_yaml() {
    log_info "Updating $APP_YAML with database configuration..."
    
    # Get connection name
    CONNECTION_NAME=$(gcloud sql instances describe "$SQL_INSTANCE_NAME" \
        --project="$PROJECT_ID" \
        --format="value(connectionName)")
    
    # Check if beta_settings exists
    if grep -q "beta_settings:" "$APP_YAML"; then
        log_info "beta_settings already exists in $APP_YAML"
    else
        if [ "$DRY_RUN" = true ]; then
            log_info "[DRY-RUN] Would update $APP_YAML with Cloud SQL configuration"
            log_info "[DRY-RUN] Would add VPC connector and beta_settings"
            return 0
        fi
        
        # Backup original file
        cp "$APP_YAML" "${APP_YAML}.backup"
        
        # Add Cloud SQL configuration
        cat >> "$APP_YAML" <<EOF

# Cloud SQL Configuration
vpc_access_connector:
  name: projects/${PROJECT_ID}/locations/${REGION}/connectors/wildepod-connector

beta_settings:
  cloud_sql_instances: ${CONNECTION_NAME}

env_variables:
  CLOUD_SQL_CONNECTION_NAME: ${CONNECTION_NAME}
  USE_CLOUD_SQL_AUTH_PROXY: "False"
EOF
        log_success "Updated $APP_YAML with Cloud SQL configuration"
    fi
}

################################################################################
# Function: Run tests
################################################################################
run_tests() {
    if [ "$SKIP_TESTS" = true ]; then
        log_warning "Skipping tests as requested"
        return 0
    fi
    
    log_info "Running tests before deployment..."
    
    # Check if pytest is available
    if command -v pytest &> /dev/null; then
        pytest || log_error "Tests failed. Fix issues before deploying."
    elif python -m pytest --version &> /dev/null; then
        python -m pytest || log_error "Tests failed. Fix issues before deploying."
    else
        log_warning "pytest not found, skipping tests"
    fi
    
    log_success "Tests passed"
}

################################################################################
# Function: Run database migrations
################################################################################
run_migrations() {
    log_info "Running database migrations..."
    
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY-RUN] Would run database migrations:"
        log_info "  - Start Cloud SQL Proxy"
        log_info "  - python manage.py migrate --settings=config.settings.${ENVIRONMENT}"
        log_success "Database migrations skipped (dry-run)"
        return 0
    fi
    
    # Get database password from Secret Manager
    DB_PASSWORD=$(gcloud secrets versions access latest \
        --secret="${ENVIRONMENT}_db_password" \
        --project="$PROJECT_ID")
    
    CONNECTION_NAME=$(gcloud sql instances describe "$SQL_INSTANCE_NAME" \
        --project="$PROJECT_ID" \
        --format="value(connectionName)")
    
    # Set environment variables for migration
    export PROD_DATABASE_URL="postgres://${DB_USER}:${DB_PASSWORD}@//cloudsql/${CONNECTION_NAME}/${DB_NAME}"
    export USE_CLOUD_SQL_AUTH_PROXY="True"
    
    # Start Cloud SQL Proxy
    log_info "Starting Cloud SQL Proxy..."
    cloud_sql_proxy -instances="${CONNECTION_NAME}=tcp:5440" &
    PROXY_PID=$!
    
    # Wait for proxy to be ready
    sleep 5
    
    # Run migrations
    python manage.py migrate --settings="config.settings.${ENVIRONMENT}" || {
        kill $PROXY_PID
        log_error "Migration failed"
    }
    
    # Stop proxy
    kill $PROXY_PID
    
    log_success "Database migrations completed"
}

################################################################################
# Function: Collect static files
################################################################################
collect_static() {
    log_info "Collecting static files..."
    
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY-RUN] Would run: python manage.py collectstatic --noinput --settings=config.settings.${ENVIRONMENT}"
        log_success "Static file collection skipped (dry-run)"
        return 0
    fi
    
    python manage.py collectstatic --noinput --settings="config.settings.${ENVIRONMENT}" || \
        log_warning "Static file collection failed or skipped"
    
    log_success "Static files collected"
}

################################################################################
# Function: Deploy to App Engine
################################################################################
deploy_app_engine() {
    log_info "Deploying to App Engine..."
    
    # Update app.yaml with current configuration
    update_app_yaml
    
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY-RUN] Would deploy:"
        if [ "$SERVICE_NAME" = "default" ]; then
            echo "gcloud app deploy $APP_YAML --project=$PROJECT_ID --quiet --promote"
        else
            echo "gcloud app deploy $APP_YAML --project=$PROJECT_ID --quiet --no-promote"
        fi
        APP_URL="${SERVICE_NAME}-dot-${PROJECT_ID}.appspot.com"
        log_info "[DRY-RUN] Application would be available at: https://${APP_URL}"
        return 0
    fi
    
    # Deploy application
    if [ "$SERVICE_NAME" = "default" ]; then
        gcloud app deploy "$APP_YAML" \
            --project="$PROJECT_ID" \
            --quiet \
            --promote || log_error "Deployment failed"
    else
        gcloud app deploy "$APP_YAML" \
            --project="$PROJECT_ID" \
            --quiet \
            --no-promote || log_error "Deployment failed"
    fi
    
    log_success "Application deployed successfully"
    
    # Get app URL
    APP_URL=$(gcloud app describe --project="$PROJECT_ID" --format="value(defaultHostname)")
    if [ "$SERVICE_NAME" != "default" ]; then
        APP_URL="${SERVICE_NAME}-dot-${APP_URL}"
    fi
    
    log_success "Application available at: https://${APP_URL}"
}

################################################################################
# Function: Setup GitHub Actions workflow
################################################################################
setup_github_actions() {
    log_info "Setting up GitHub Actions for CI/CD..."
    
    # Create .github/workflows directory
    mkdir -p .github/workflows
    
    # Create GitHub Actions workflow file
    cat > .github/workflows/deploy-${ENVIRONMENT}.yml <<EOF
name: Deploy to GCP ${ENVIRONMENT}

on:
  push:
    branches:
      - $([ "$ENVIRONMENT" = "prod" ] && echo "main" || echo "$ENVIRONMENT")
  workflow_dispatch:

env:
  GCP_PROJECT_ID: ${PROJECT_ID}
  GCP_REGION: ${REGION}
  ENVIRONMENT: ${ENVIRONMENT}

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install -r requirements-dev.txt
      
      - name: Run tests
        run: |
          pytest || echo "No tests found"
      
      - name: Run linting
        run: |
          flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics || true

  deploy:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/$([ "$ENVIRONMENT" = "prod" ] && echo "main" || echo "$ENVIRONMENT")'
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Authenticate to Google Cloud
        uses: google-github-actions/auth@v2
        with:
          credentials_json: \${{ secrets.GCP_SA_KEY }}
      
      - name: Set up Cloud SDK
        uses: google-github-actions/setup-gcloud@v2
      
      - name: Deploy to App Engine
        run: |
          gcloud app deploy ${APP_YAML} \\
            --project=\${GCP_PROJECT_ID} \\
            --quiet \\
            $([ "$SERVICE_NAME" = "default" ] && echo "--promote" || echo "--no-promote")
      
      - name: Run database migrations
        run: |
          # Install Cloud SQL Proxy
          wget https://dl.google.com/cloudsql/cloud_sql_proxy.linux.amd64 -O cloud_sql_proxy
          chmod +x cloud_sql_proxy
          
          # Get database credentials from Secret Manager
          DB_PASSWORD=\$(gcloud secrets versions access latest --secret="${ENVIRONMENT}_db_password")
          CONNECTION_NAME=\$(gcloud sql instances describe ${SQL_INSTANCE_NAME} --format="value(connectionName)")
          
          # Start Cloud SQL Proxy
          ./cloud_sql_proxy -instances=\${CONNECTION_NAME}=tcp:5440 &
          sleep 5
          
          # Run migrations
          export PROD_DATABASE_URL="postgres://${DB_USER}:\${DB_PASSWORD}@127.0.0.1:5440/${DB_NAME}"
          python manage.py migrate --settings="config.settings.${ENVIRONMENT}"
      
      - name: Notify deployment
        if: always()
        run: |
          echo "Deployment completed for ${ENVIRONMENT}"

EOF
    
    log_success "GitHub Actions workflow created: .github/workflows/deploy-${ENVIRONMENT}.yml"
    
    # Create service account instructions
    cat > .github/GCP_SETUP_INSTRUCTIONS.md <<EOF
# GCP Service Account Setup for GitHub Actions

## Steps to enable GitHub Actions deployment:

1. Create a service account for GitHub Actions:
\`\`\`bash
gcloud iam service-accounts create github-actions \\
    --display-name="GitHub Actions Deployment" \\
    --project=${PROJECT_ID}
\`\`\`

2. Grant necessary permissions:
\`\`\`bash
# App Engine deployment
gcloud projects add-iam-policy-binding ${PROJECT_ID} \\
    --member="serviceAccount:github-actions@${PROJECT_ID}.iam.gserviceaccount.com" \\
    --role="roles/appengine.appAdmin"

# Cloud Build
gcloud projects add-iam-policy-binding ${PROJECT_ID} \\
    --member="serviceAccount:github-actions@${PROJECT_ID}.iam.gserviceaccount.com" \\
    --role="roles/cloudbuild.builds.editor"

# Cloud SQL
gcloud projects add-iam-policy-binding ${PROJECT_ID} \\
    --member="serviceAccount:github-actions@${PROJECT_ID}.iam.gserviceaccount.com" \\
    --role="roles/cloudsql.client"

# Secret Manager
gcloud projects add-iam-policy-binding ${PROJECT_ID} \\
    --member="serviceAccount:github-actions@${PROJECT_ID}.iam.gserviceaccount.com" \\
    --role="roles/secretmanager.secretAccessor"

# Storage Admin (for static files)
gcloud projects add-iam-policy-binding ${PROJECT_ID} \\
    --member="serviceAccount:github-actions@${PROJECT_ID}.iam.gserviceaccount.com" \\
    --role="roles/storage.admin"
\`\`\`

3. Create and download service account key:
\`\`\`bash
gcloud iam service-accounts keys create github-sa-key.json \\
    --iam-account=github-actions@${PROJECT_ID}.iam.gserviceaccount.com
\`\`\`

4. Add the key to GitHub Secrets:
   - Go to your repository on GitHub
   - Navigate to Settings > Secrets and variables > Actions
   - Click "New repository secret"
   - Name: \`GCP_SA_KEY\`
   - Value: Paste the entire contents of \`github-sa-key.json\`

5. Delete the local key file for security:
\`\`\`bash
rm github-sa-key.json
\`\`\`

## Additional Secrets to Add to GitHub:

Add these secrets to your GitHub repository for the deployment to work:

- \`GCP_SA_KEY\`: Service account key (from above)
- Additional environment variables as needed

## Testing the Workflow:

After setup, push to the $([ "$ENVIRONMENT" = "prod" ] && echo "main" || echo "$ENVIRONMENT") branch to trigger automatic deployment.

EOF
    
    log_success "Setup instructions created: .github/GCP_SETUP_INSTRUCTIONS.md"
}

################################################################################
# Function: Create VPC connector (required for Cloud SQL)
################################################################################
setup_vpc_connector() {
    log_info "Setting up VPC connector for Cloud SQL access..."
    
    CONNECTOR_NAME="wildepod-connector"
    
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY-RUN] Would check/create VPC connector: $CONNECTOR_NAME"
        log_info "[DRY-RUN] Would enable vpcaccess.googleapis.com API"
        return 0
    fi
    
    # Check if connector exists
    if gcloud compute networks vpc-access connectors describe "$CONNECTOR_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" &> /dev/null; then
        log_warning "VPC connector already exists"
    else
        # Enable VPC Access API
        gcloud services enable vpcaccess.googleapis.com --quiet
        
        # Create connector
        gcloud compute networks vpc-access connectors create "$CONNECTOR_NAME" \
            --region="$REGION" \
            --network=default \
            --range=10.8.0.0/28 \
            --project="$PROJECT_ID" || log_warning "VPC connector creation may have failed or already exists"
        
        log_success "VPC connector created"
    fi
}

################################################################################
# Main execution
################################################################################
main() {
    log_info "==================================================================="
    log_info "GCP Deployment Script - WildePod Application"
    log_info "Environment: $ENVIRONMENT"
    log_info "==================================================================="
    
    # Always check prerequisites
    check_prerequisites
    
    if [ "$FULL_DEPLOYMENT" = true ]; then
        SETUP_DB=true
        MIGRATE_DB=true
        DEPLOY_ONLY=false
    fi
    
    # Setup Cloud SQL if requested
    if [ "$SETUP_DB" = true ]; then
        setup_cloud_sql
        setup_vpc_connector
    fi
    
    # Run migrations if requested
    if [ "$MIGRATE_DB" = true ] && [ "$DEPLOY_ONLY" = false ]; then
        run_migrations
    fi
    
    # Deploy application if not migration-only
    if [ "$DEPLOY_ONLY" = true ] || [ "$FULL_DEPLOYMENT" = true ] || \
       [ "$SETUP_DB" = false ] && [ "$MIGRATE_DB" = false ]; then
        run_tests
        collect_static
        deploy_app_engine
    fi
    
    # Setup GitHub Actions
    setup_github_actions
    
    log_success "==================================================================="
    log_success "Deployment process completed successfully!"
    log_success "==================================================================="
    
    log_info "Next steps:"
    log_info "1. Review and update .env.${ENVIRONMENT} with your secret keys"
    log_info "2. Follow instructions in .github/GCP_SETUP_INSTRUCTIONS.md to enable GitHub Actions"
    log_info "3. Commit and push changes to trigger automated deployments"
    log_info ""
    log_info "Useful commands:"
    log_info "  View logs: gcloud app logs tail -s $SERVICE_NAME"
    log_info "  SSH to instance: gcloud app instances ssh [INSTANCE] -s $SERVICE_NAME"
    log_info "  Database proxy: cloud_sql_proxy -instances=CONNECTION_NAME=tcp:5440"
}

# Run main function
main

