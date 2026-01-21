#!/bin/bash

################################################################################
# WildePod Post-Deployment Setup Script
# 
# This script completes the setup after initial App Engine deployment:
# - Runs database migrations
# - Sets up Cloud Storage for media files
# - Collects static files
# - Creates superuser account
# - Configures secrets
# - Tests the deployment
################################################################################

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Configuration
ENVIRONMENT="${1:-jnovak-dev}"
PROJECT_ID="wildepod-339517"
REGION="us-west2"
DB_INSTANCE="wildepoddb"
SERVICE_NAME="${ENVIRONMENT}"

# Derived variables
DB_NAME="wildepod_${ENVIRONMENT//-/_}"
DB_USER="wildepod_${ENVIRONMENT//-/_}_user"
BUCKET_NAME="${PROJECT_ID}-${ENVIRONMENT}-media"
CONNECTION_NAME="${PROJECT_ID}:${REGION}:${DB_INSTANCE}"
SETTINGS_MODULE="config.settings.${ENVIRONMENT//-/_}"

echo -e "${CYAN}================================${NC}"
echo -e "${CYAN}WildePod Post-Deployment Setup${NC}"
echo -e "${CYAN}Environment: ${ENVIRONMENT}${NC}"
echo -e "${CYAN}================================${NC}"
echo ""

# Function to print status messages
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Check if gcloud is authenticated
print_status "Checking gcloud authentication..."
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
    print_error "Not authenticated with gcloud. Run: gcloud auth login"
    exit 1
fi

# Check Application Default Credentials for Cloud SQL Proxy
if ! gcloud auth application-default print-access-token &>/dev/null; then
    print_status "Setting up Application Default Credentials for Cloud SQL Proxy..."
    print_warning "You may need to authenticate in your browser"
    gcloud auth application-default login
fi
print_success "Authenticated"

# Set project
print_status "Setting GCP project to ${PROJECT_ID}..."
gcloud config set project ${PROJECT_ID}
print_success "Project set"

echo ""
echo -e "${CYAN}================================${NC}"
echo -e "${CYAN}Step 1: Database Setup${NC}"
echo -e "${CYAN}================================${NC}"
echo ""

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    print_status "Activating virtual environment..."
    source .venv/bin/activate
    print_success "Virtual environment activated"
elif [ -d "venv" ]; then
    print_status "Activating virtual environment..."
    source venv/bin/activate
    print_success "Virtual environment activated"
else
    print_warning "No virtual environment found. Make sure Django is installed."
fi

# Get database password from Secret Manager
print_status "Retrieving database password from Secret Manager..."
DB_PASSWORD=$(gcloud secrets versions access latest --secret="${ENVIRONMENT}_db_password" 2>/dev/null || echo "")

if [ -z "$DB_PASSWORD" ]; then
    print_warning "Database password not found in Secret Manager"
    echo -n "Enter database password (or press Enter to skip migrations): "
    read -s DB_PASSWORD
    echo ""
fi

if [ -n "$DB_PASSWORD" ]; then
    # Check if Cloud SQL Proxy is available
    if ! command -v cloud-sql-proxy &> /dev/null; then
        print_status "Installing Cloud SQL Proxy v2..."
        curl -o cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.14.2/cloud-sql-proxy.linux.amd64
        chmod +x cloud-sql-proxy
        sudo mv cloud-sql-proxy /usr/local/bin/ 2>/dev/null || mv cloud-sql-proxy ~/bin/ 2>/dev/null || true
    fi

    # Start Cloud SQL Proxy on port 5433 to avoid conflicts
    print_status "Starting Cloud SQL Proxy..."
    # Kill any existing process on port 5433
    lsof -ti:5433 | xargs kill -9 2>/dev/null || true
    sleep 1
    cloud-sql-proxy --port 5433 ${CONNECTION_NAME} &
    PROXY_PID=$!
    sleep 5

    # URL-encode the password for use in connection string
    DB_PASSWORD_ENCODED=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${DB_PASSWORD}', safe=''))")
    
    # Set database URL
    export DATABASE_URL="postgres://${DB_USER}:${DB_PASSWORD_ENCODED}@127.0.0.1:5433/${DB_NAME}"
    export JNOVAK_DEV_DATABASE_URL="postgres://${DB_USER}:${DB_PASSWORD_ENCODED}@127.0.0.1:5433/${DB_NAME}"
    export GOOGLE_CLOUD_PROJECT="${PROJECT_ID}"
    
    # Run migrations
    print_status "Running database migrations..."
    if python3 manage.py migrate --settings=${SETTINGS_MODULE} --noinput; then
        print_success "Migrations completed successfully"
    else
        print_error "Migrations failed"
        kill $PROXY_PID 2>/dev/null || true
        exit 1
    fi

    # Stop proxy
    kill $PROXY_PID 2>/dev/null || true
    print_success "Database setup completed"
else
    print_warning "Skipping migrations - no database password provided"
fi

echo ""
echo -e "${CYAN}================================${NC}"
echo -e "${CYAN}Step 2: Cloud Storage Setup${NC}"
echo -e "${CYAN}================================${NC}"
echo ""

# Create Cloud Storage bucket
print_status "Checking if bucket exists: ${BUCKET_NAME}..."
if gsutil ls -b gs://${BUCKET_NAME} &>/dev/null; then
    print_warning "Bucket already exists: ${BUCKET_NAME}"
else
    print_status "Creating Cloud Storage bucket: ${BUCKET_NAME}..."
    if gsutil mb -l ${REGION} gs://${BUCKET_NAME}/; then
        print_success "Bucket created successfully"
        
        # Set bucket permissions for public read
        print_status "Setting bucket permissions..."
        gsutil iam ch allUsers:objectViewer gs://${BUCKET_NAME}/
        print_success "Bucket permissions set"
        
        # Set CORS configuration
        print_status "Setting CORS configuration..."
        cat > /tmp/cors.json <<EOF
[
  {
    "origin": ["*"],
    "method": ["GET", "HEAD"],
    "responseHeader": ["Content-Type"],
    "maxAgeSeconds": 3600
  }
]
EOF
        gsutil cors set /tmp/cors.json gs://${BUCKET_NAME}/
        rm /tmp/cors.json
        print_success "CORS configuration set"
    else
        print_error "Failed to create bucket"
    fi
fi

echo ""
echo -e "${CYAN}================================${NC}"
echo -e "${CYAN}Step 3: Static Files${NC}"
echo -e "${CYAN}================================${NC}"
echo ""

# Collect static files
print_status "Collecting static files..."
if python3 manage.py collectstatic --settings=${SETTINGS_MODULE} --noinput 2>/dev/null; then
    print_success "Static files collected"
else
    print_warning "Static file collection failed or skipped"
fi

echo ""
echo -e "${CYAN}================================${NC}"
echo -e "${CYAN}Step 4: Superuser Creation${NC}"
echo -e "${CYAN}================================${NC}"
echo ""

if [ -n "$DB_PASSWORD" ]; then
    print_status "Creating superuser via Cloud SQL Proxy..."
    
    # Start Cloud SQL Proxy again if needed
    if ! pgrep -f "cloud-sql-proxy.*${CONNECTION_NAME}" > /dev/null; then
        print_status "Restarting Cloud SQL Proxy..."
        cloud-sql-proxy --port 5433 ${CONNECTION_NAME} &
        PROXY_PID=$!
        sleep 5
    fi
    
    # Set environment variables
    export JNOVAK_DEV_DATABASE_URL="postgres://${DB_USER}:${DB_PASSWORD_ENCODED}@127.0.0.1:5433/${DB_NAME}"
    export GOOGLE_CLOUD_PROJECT="${PROJECT_ID}"
    export DJANGO_SUPERUSER_PASSWORD="letmein"
    
    # Create superuser non-interactively using createsuperuser command
    print_status "Creating superuser: jnovak-dev@example.com"
    export DJANGO_SUPERUSER_EMAIL="jnovak-dev@example.com"
    export DJANGO_SUPERUSER_PASSWORD="letmein"
    
    # Try createsuperuser, ignore if already exists
    python3 manage.py createsuperuser --noinput --email jnovak-dev@example.com --name "John Novak" 2>&1 | grep -v "already exists" || true
    SUPERUSER_RESULT=$?
    
    # Stop proxy if we started it
    if [ -n "$PROXY_PID" ]; then
        kill $PROXY_PID 2>/dev/null || true
    fi
    
    if [ $SUPERUSER_RESULT -eq 0 ]; then
        print_success "Superuser created: jnovak-dev@example.com / letmein"
    else
        print_warning "Superuser creation failed"
    fi
else
    print_status "Checking if we can create superuser via SSH..."
    INSTANCE_ID=$(gcloud app instances list --service=${SERVICE_NAME} --format="value(id)" --limit=1 2>/dev/null || echo "")

    if [ -n "$INSTANCE_ID" ]; then
        print_status "Found instance: ${INSTANCE_ID}"
        echo ""
        echo -e "${YELLOW}To create a superuser, run this command:${NC}"
        echo -e "${GREEN}gcloud app instances ssh ${INSTANCE_ID} --service=${SERVICE_NAME}${NC}"
        echo ""
        echo -e "${YELLOW}Then inside the instance, run:${NC}"
        echo -e "${GREEN}python manage.py createsuperuser --settings=${SETTINGS_MODULE}${NC}"
        echo ""
        echo -n "Press Enter to continue after creating superuser (or 's' to skip): "
        read -r response
        if [ "$response" = "s" ]; then
            print_warning "Skipped superuser creation"
        fi
    else
        print_warning "No running instances found and no database password available."
        print_status "You can create a superuser later by running:"
        echo "  ./post_deploy_setup.sh ${ENVIRONMENT}"
    fi
fi

echo ""
echo -e "${CYAN}================================${NC}"
echo -e "${CYAN}Step 5: Environment Secrets${NC}"
echo -e "${CYAN}================================${NC}"
echo ""

print_status "Checking required secrets..."

# Function to create/update secret
create_or_update_secret() {
    local secret_name=$1
    local secret_description=$2
    local auto_generate=$3
    local secret_value=""
    
    if gcloud secrets describe ${secret_name} &>/dev/null; then
        print_warning "Secret '${secret_name}' already exists"
        echo -n "Update it? (y/N): "
        read -r update_secret
        if [ "$update_secret" = "y" ] || [ "$update_secret" = "Y" ]; then
            if [ "$auto_generate" = "true" ]; then
                secret_value=$(python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')
                print_status "Auto-generated secret key"
            else
                echo -n "Enter ${secret_description}: "
                read -s secret_value
                echo ""
            fi
            if [ -n "$secret_value" ]; then
                echo -n "$secret_value" | gcloud secrets versions add ${secret_name} --data-file=-
                print_success "Secret updated"
            fi
        fi
    else
        if [ "$auto_generate" = "true" ]; then
            secret_value=$(python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')
            print_status "Auto-generating ${secret_description}..."
        else
            echo -n "Enter ${secret_description} (or press Enter to skip): "
            read -s secret_value
            echo ""
        fi
        if [ -n "$secret_value" ]; then
            echo -n "$secret_value" | gcloud secrets create ${secret_name} --data-file=- --replication-policy="automatic"
            print_success "Secret created"
        else
            print_warning "Skipped ${secret_name}"
        fi
    fi
}

# Django secret key
SECRET_NAME="${ENVIRONMENT//-/_}_django_secret"
create_or_update_secret ${SECRET_NAME} "Django Secret Key" "true"

# Dropbox credentials (optional)
echo ""
echo -n "Configure Dropbox integration? (y/N): "
read -r configure_dropbox
if [ "$configure_dropbox" = "y" ] || [ "$configure_dropbox" = "Y" ]; then
    create_or_update_secret "dropbox_app_key_${ENVIRONMENT//-/_}" "Dropbox App Key"
    create_or_update_secret "dropbox_app_secret_${ENVIRONMENT//-/_}" "Dropbox App Secret"
    create_or_update_secret "dropbox_refresh_token_${ENVIRONMENT//-/_}" "Dropbox Refresh Token"
fi

echo ""
echo -e "${CYAN}================================${NC}"
echo -e "${CYAN}Step 6: Verification${NC}"
echo -e "${CYAN}================================${NC}"
echo ""

# Test the deployment
APP_URL="https://${SERVICE_NAME}-dot-${PROJECT_ID}.appspot.com"
print_status "Testing deployment at: ${APP_URL}"

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" ${APP_URL} || echo "000")

if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "302" ]; then
    print_success "Application is responding (HTTP ${HTTP_CODE})"
elif [ "$HTTP_CODE" = "500" ]; then
    print_error "Application returned 500 error - check logs"
    print_status "View logs with: gcloud app logs tail -s ${SERVICE_NAME}"
else
    print_warning "Application returned HTTP ${HTTP_CODE}"
fi

# Check recent logs
print_status "Recent application logs:"
echo ""
gcloud app logs read --service=${SERVICE_NAME} --limit=10 --format="table(timestamp,severity,message)" 2>/dev/null || print_warning "Could not fetch logs"

echo ""
echo -e "${CYAN}================================${NC}"
echo -e "${GREEN}Setup Complete!${NC}"
echo -e "${CYAN}================================${NC}"
echo ""

print_status "Application URL: ${APP_URL}"
print_status "Admin interface: ${APP_URL}/admin/"
echo ""
print_status "Useful commands:"
echo "  View logs:       gcloud app logs tail -s ${SERVICE_NAME}"
echo "  SSH to instance: gcloud app instances ssh INSTANCE_ID -s ${SERVICE_NAME}"
echo "  List instances:  gcloud app instances list -s ${SERVICE_NAME}"
echo "  Browse app:      gcloud app browse -s ${SERVICE_NAME}"
echo ""
print_status "Database connection:"
echo "  Instance:  ${DB_INSTANCE}"
echo "  Database:  ${DB_NAME}"
echo "  User:      ${DB_USER}"
echo "  Connect:   cloud-sql-proxy --port 5433 ${CONNECTION_NAME}"
echo ""
print_status "Cloud Storage:"
echo "  Bucket:    gs://${BUCKET_NAME}/"
echo "  List:      gsutil ls gs://${BUCKET_NAME}/"
echo ""

# Save configuration to file
CONFIG_FILE=".env.${ENVIRONMENT}"
if [ ! -f "$CONFIG_FILE" ]; then
    print_status "Creating ${CONFIG_FILE} with configuration..."
    cat > ${CONFIG_FILE} <<EOF
# WildePod Environment Configuration
# Generated on $(date)

# Django
DJANGO_SETTINGS_MODULE="${SETTINGS_MODULE}"
DJANGO_SECRET_KEY="<retrieve from Secret Manager: ${ENVIRONMENT//-/_}_django_secret>"

# Database
DATABASE_URL="postgres://${DB_USER}:PASSWORD@//${DB_NAME}?host=/cloudsql/${CONNECTION_NAME}"
CLOUD_SQL_CONNECTION_NAME="${CONNECTION_NAME}"

# Storage
GS_BUCKET_NAME="${BUCKET_NAME}"
MEDIA_URL="https://storage.googleapis.com/${BUCKET_NAME}/media/"

# Dropbox (optional)
DROPBOX_APP_KEY="<retrieve from Secret Manager if configured>"
DROPBOX_APP_SECRET="<retrieve from Secret Manager if configured>"
DROPBOX_REFRESH_TOKEN="<retrieve from Secret Manager if configured>"

# Application
ALLOWED_HOSTS="${SERVICE_NAME}-dot-${PROJECT_ID}.appspot.com"
DEBUG="False"
EOF
    print_success "Configuration saved to ${CONFIG_FILE}"
fi

echo -e "${GREEN}All steps completed!${NC}"
echo ""
