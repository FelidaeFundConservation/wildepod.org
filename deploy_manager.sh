#!/bin/bash
# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

################################################################################
































































































































































































          fi            echo "⚠️ Deployment completed with warnings or was skipped"          else            echo "URL: https://jnovak-dev-dot-${GCP_PROJECT_ID}.appspot.com"            echo "✅ Deployment to jnovak-dev successful!"          if [ "${{ needs.migrate.result }}" = "success" ]; then        run: |      - name: Deployment Status    steps:        if: always()    needs: [migrate]    runs-on: ubuntu-latest    name: Notification  notify:  # Job 4: Notify          fi            echo "Database credentials not found, skipping migrations"          else            fi              echo "Database instance not found, skipping migrations"            else              kill $PROXY_PID || true              # Stop proxy                            python manage.py migrate --settings=config.settings.jnovak_dev --noinput              # Run migrations                            export JNOVAK_DEV_DATABASE_URL="postgres://wildepod_jnovak_dev_user:${DB_PASSWORD}@127.0.0.1:5440/wildepod_jnovak_dev"              # Set database URL                            sleep 10              # Wait for proxy to be ready                            PROXY_PID=$!              ./cloud_sql_proxy -instances=${CONNECTION_NAME}=tcp:5440 &              # Start Cloud SQL Proxy in background            if [ -n "$CONNECTION_NAME" ]; then                        CONNECTION_NAME=$(gcloud sql instances describe wildepod-jnovak-dev-db --project=$GCP_PROJECT_ID --format="value(connectionName)" || echo "")          if [ -n "$DB_PASSWORD" ]; then                    DB_PASSWORD=$(gcloud secrets versions access latest --secret="jnovak_dev_db_password" --project=$GCP_PROJECT_ID || echo "")          # Get database credentials        run: |          DJANGO_SECRET_KEY: ${{ secrets.DJANGO_SECRET_KEY }}        env:      - name: Run database migrations                chmod +x cloud_sql_proxy          wget https://dl.google.com/cloudsql/cloud_sql_proxy.linux.amd64 -O cloud_sql_proxy        run: |      - name: Install Cloud SQL Proxy                pip install -r requirements.txt          python -m pip install --upgrade pip        run: |      - name: Install dependencies              uses: google-github-actions/setup-gcloud@v2      - name: Set up Cloud SDK                credentials_json: ${{ secrets.GCP_SA_KEY }}        with:        uses: google-github-actions/auth@v2      - name: Authenticate to Google Cloud                python-version: ${{ env.PYTHON_VERSION }}        with:        uses: actions/setup-python@v5      - name: Set up Python              uses: actions/checkout@v4      - name: Checkout code    steps:        if: github.event_name == 'push' || github.event_name == 'workflow_dispatch'    needs: deploy    runs-on: ubuntu-latest    name: Database Migrations  migrate:  # Job 3: Run database migrations          echo "version=$VERSION" >> $GITHUB_OUTPUT          echo "url=$URL" >> $GITHUB_OUTPUT          URL="https://${VERSION}-dot-jnovak-dev-dot-${GCP_PROJECT_ID}.appspot.com"          VERSION=$(echo $GITHUB_SHA | cut -c1-7)        run: |        id: deployment      - name: Get deployment info                  --version=$(echo $GITHUB_SHA | cut -c1-7)            --no-promote \            --quiet \            --project=$GCP_PROJECT_ID \          gcloud app deploy jnovak-dev.yaml \        run: |      - name: Deploy to App Engine                python manage.py collectstatic --noinput --settings=config.settings.jnovak_dev || echo "Static collection skipped"        run: |          DJANGO_SECRET_KEY: ${{ secrets.DJANGO_SECRET_KEY }}        env:        continue-on-error: true      - name: Collect static files                pip install -r requirements.txt          python -m pip install --upgrade pip        run: |      - name: Install dependencies              uses: google-github-actions/setup-gcloud@v2      - name: Set up Cloud SDK                credentials_json: ${{ secrets.GCP_SA_KEY }}        with:        uses: google-github-actions/auth@v2      - name: Authenticate to Google Cloud                python-version: ${{ env.PYTHON_VERSION }}        with:        uses: actions/setup-python@v5      - name: Set up Python              uses: actions/checkout@v4      - name: Checkout code    steps:          url: https://jnovak-dev-dot-${{ secrets.GCP_PROJECT_ID }}.appspot.com      name: jnovak-dev    environment:    if: github.event_name == 'push' || github.event_name == 'workflow_dispatch'    runs-on: ubuntu-latest    needs: test  deploy:  # Job 2: Deploy to App Engine          pytest -v --tb=short || echo "Some tests failed but continuing"        run: |        if: github.event.inputs.skip_tests != 'true'      - name: Run tests                flake8 . --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics          flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics          pip install flake8        run: |        continue-on-error: true      - name: Run linting (flake8)                pip install -r requirements-dev.txt          pip install -r requirements.txt          python -m pip install --upgrade pip        run: |      - name: Install dependencies                cache: 'pip'          python-version: ${{ env.PYTHON_VERSION }}        with:        uses: actions/setup-python@v5      - name: Set up Python              uses: actions/checkout@v4      - name: Checkout code    steps:        runs-on: ubuntu-latest    name: Test and Quality Checks  test:  # Job 1: Run tests and quality checksjobs:  PYTHON_VERSION: '3.10'  ENVIRONMENT: jnovak-dev  GCP_REGION: us-central1  GCP_PROJECT_ID: ${{ secrets.GCP_PROJECT_ID }}env:        default: 'false'        required: false        description: 'Skip tests before deployment'      skip_tests:    inputs:  workflow_dispatch:      - jnovak-dev    branches:  pull_request:      - jnovak-dev    branches:  push:on:# GCP Deployment Manager - Interactive Helper Script
# 
# This script provides an interactive menu for managing GCP deployments
################################################################################

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

clear
echo -e "${CYAN}"
cat << "EOF"
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║         GCP Deployment Manager - WildePod                 ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"

# Check if scripts exist
if [ ! -f "deploy_gcp.sh" ]; then
    echo -e "${RED}Error: deploy_gcp.sh not found${NC}"
    exit 1
fi

# Function to display menu
show_menu() {
    echo -e "${BLUE}Select an option:${NC}\n"
    echo "  1) 🚀 Full deployment (first-time setup)"
    echo "  2) 📦 Deploy application only"
    echo "  3) 🗄️  Setup database only"
    echo "  4) 🔄 Run migrations only"
    echo "  5) ✅ Run pre-deployment checks"
    echo "  6) 📊 View logs"
    echo "  7) 💾 Database operations"
    echo "  8) 📝 View documentation"
    echo "  9) ⚙️  Configuration"
    echo "  0) 🚪 Exit"
    echo ""
}

# Function to select environment
select_environment() {
    echo -e "${BLUE}Select environment:${NC}\n"
    echo "  1) Staging"
    echo "  2) Production"
    echo "  3) Bhutan"
    echo "  4) JNovak-Dev"
    echo ""
    read -p "Choice [1]: " env_choice
    env_choice=${env_choice:-1}
    
    case $env_choice in
        1) echo "staging" ;;
        2) echo "prod" ;;
        3) echo "bhutan" ;;
        4) echo "jnovak-dev" ;;
        *) echo "staging" ;;
    esac
}

# Function to confirm action
confirm() {
    read -p "$1 (y/n) [n]: " -n 1 -r
    echo
    [[ $REPLY =~ ^[Yy]$ ]]
}

# Main menu loop
while true; do
    show_menu
    read -p "Enter choice [0]: " choice
    choice=${choice:-0}
    
    case $choice in
        1)
            echo -e "\n${YELLOW}═══ Full Deployment (First-Time Setup) ═══${NC}\n"
            ENV=$(select_environment)
            
            if confirm "This will create Cloud SQL, VPC, and deploy to $ENV. Continue?"; then
                ./deploy_gcp.sh "$ENV" --full
                echo -e "\n${GREEN}✓ Deployment complete!${NC}"
                echo -e "Next: Update .env.$ENV with your secrets"
                read -p "Press Enter to continue..."
            fi
            ;;
            
        2)
            echo -e "\n${YELLOW}═══ Deploy Application Only ═══${NC}\n"
            ENV=$(select_environment)
            
            echo -e "${CYAN}Options:${NC}"
            read -p "Skip tests? (y/n) [n]: " skip_tests
            read -p "Dry-run first? (y/n) [y]: " dry_run
            
            CMD="./deploy_gcp.sh $ENV --deploy-only"
            [[ $skip_tests =~ ^[Yy]$ ]] && CMD="$CMD --skip-tests"
            
            # Run dry-run if requested
            if [[ ! $dry_run =~ ^[Nn]$ ]]; then
                echo -e "\n${YELLOW}Running dry-run first...${NC}\n"
                $CMD --dry-run
                echo ""
                if ! confirm "Proceed with actual deployment?"; then
                    echo "Deployment cancelled"
                    read -p "Press Enter to continue..."
                    continue
                fi
            fi
            
            if confirm "Deploy to $ENV?"; then
                $CMD
                echo -e "\n${GREEN}✓ Deployment complete!${NC}"
                read -p "Press Enter to continue..."
            fi
            ;;
            
        3)
            echo -e "\n${YELLOW}═══ Setup Database Only ═══${NC}\n"
            ENV=$(select_environment)
            
            echo -e "${CYAN}Database setup options:${NC}"
            echo "  1) Create new Cloud SQL instance"
            echo "  2) Use existing Cloud SQL instance"
            read -p "Choice [1]: " db_setup_choice
            
            if [ "${db_setup_choice:-1}" = "2" ]; then
                # Show available instances
                echo -e "\n${CYAN}Available Cloud SQL instances:${NC}"
                gcloud sql instances list --project="${GCP_PROJECT_ID:-wildepod-project}" --format="table(name,region,databaseVersion)" 2>/dev/null || echo "  (Unable to list instances)"
                echo ""
                read -p "Enter instance name: " instance_name
                
                if [ -n "$instance_name" ]; then
                    if confirm "Use existing instance '$instance_name' for $ENV?"; then
                        ./deploy_gcp.sh "$ENV" --use-existing-db "$instance_name"
                        echo -e "\n${GREEN}✓ Database setup complete!${NC}"
                    fi
                fi
            else
                if confirm "Create Cloud SQL instance for $ENV?"; then
                    ./deploy_gcp.sh "$ENV" --setup-db
                    echo -e "\n${GREEN}✓ Database setup complete!${NC}"
                fi
            fi
            read -p "Press Enter to continue..."
            ;;
            
        4)
            echo -e "\n${YELLOW}═══ Run Database Migrations ═══${NC}\n"
            ENV=$(select_environment)
            
            if confirm "Run migrations on $ENV database?"; then
                ./deploy_gcp.sh "$ENV" --migrate-db
                echo -e "\n${GREEN}✓ Migrations complete!${NC}"
                read -p "Press Enter to continue..."
            fi
            ;;
            
        5)
            echo -e "\n${YELLOW}═══ Pre-Deployment Checks ═══${NC}\n"
            ENV=$(select_environment)
            
            ./pre_deploy_check.sh "$ENV"
            read -p "Press Enter to continue..."
            ;;
            
        6)
            echo -e "\n${YELLOW}═══ View Logs ═══${NC}\n"
            ENV=$(select_environment)
            
            echo -e "${BLUE}Log options:${NC}"
            echo "  1) Tail logs (real-time)"
            echo "  2) Read recent logs"
            echo "  3) Error logs only"
            read -p "Choice [1]: " log_choice
            
            if [ -z "$GCP_PROJECT_ID" ]; then
                read -p "Enter GCP Project ID: " GCP_PROJECT_ID
                export GCP_PROJECT_ID
            fi
            
            SERVICE=$([ "$ENV" = "prod" ] && echo "default" || echo "$ENV")
            
            case ${log_choice:-1} in
                1) gcloud app logs tail -s "$SERVICE" ;;
                2) gcloud app logs read -s "$SERVICE" --limit=50 ;;
                3) gcloud app logs read -s "$SERVICE" --severity=ERROR --limit=20 ;;
            esac
            
            read -p "Press Enter to continue..."
            ;;
            
        7)
            echo -e "\n${YELLOW}═══ Database Operations ═══${NC}\n"
            ENV=$(select_environment)
            
            echo -e "${BLUE}Database operations:${NC}"
            echo "  1) Connect to database (Cloud SQL Proxy)"
            echo "  2) Create backup"
            echo "  3) List backups"
            echo "  4) View database info"
            read -p "Choice [1]: " db_choice
            
            if [ -z "$GCP_PROJECT_ID" ]; then
                read -p "Enter GCP Project ID: " GCP_PROJECT_ID
                export GCP_PROJECT_ID
            fi
            
            case $ENV in
                staging) INSTANCE="wildepod-staging-db" ;;
                prod) INSTANCE="wildepod-prod-db" ;;
                bhutan) INSTANCE="wildepod-bhutan-db" ;;
            esac
            
            case ${db_choice:-1} in
                1)
                    echo -e "${CYAN}Starting Cloud SQL Proxy...${NC}"
                    CONNECTION=$(gcloud sql instances describe "$INSTANCE" --format="value(connectionName)")
                    echo "Connection: $CONNECTION"
                    echo "Run this command:"
                    echo "  cloud_sql_proxy -instances=$CONNECTION=tcp:5432"
                    read -p "Press Enter to continue..."
                    ;;
                2)
                    if confirm "Create backup for $INSTANCE?"; then
                        gcloud sql backups create --instance="$INSTANCE" --description="Manual backup $(date +%Y-%m-%d)"
                        echo -e "${GREEN}✓ Backup created${NC}"
                    fi
                    read -p "Press Enter to continue..."
                    ;;
                3)
                    gcloud sql backups list --instance="$INSTANCE"
                    read -p "Press Enter to continue..."
                    ;;
                4)
                    gcloud sql instances describe "$INSTANCE"
                    read -p "Press Enter to continue..."
                    ;;
            esac
            ;;
            
        8)
            echo -e "\n${YELLOW}═══ Documentation ═══${NC}\n"
            echo "Available documentation:"
            echo "  1) DEPLOYMENT_README.md - Quick start guide"
            echo "  2) DEPLOYMENT.md - Comprehensive guide"
            echo "  3) QUICK_REFERENCE.md - Command reference"
            echo "  4) DEPLOYMENT_SYSTEM_SUMMARY.md - System overview"
            read -p "Open which file? [1]: " doc_choice
            
            case ${doc_choice:-1} in
                1) less DEPLOYMENT_README.md ;;
                2) less DEPLOYMENT.md ;;
                3) less QUICK_REFERENCE.md ;;
                4) less DEPLOYMENT_SYSTEM_SUMMARY.md ;;
            esac
            ;;
            
        9)
            echo -e "\n${YELLOW}═══ Configuration ═══${NC}\n"
            echo "Current configuration:"
            echo "  GCP_PROJECT_ID: ${GCP_PROJECT_ID:-not set}"
            echo "  GCP_REGION: ${GCP_REGION:-us-central1}"
            echo ""
            echo "Options:"
            echo "  1) Set GCP Project ID"
            echo "  2) Set GCP Region"
            echo "  3) Edit environment file"
            echo "  4) View configuration"
            read -p "Choice: " config_choice
            
            case $config_choice in
                1)
                    read -p "Enter GCP Project ID: " project_id
                    export GCP_PROJECT_ID="$project_id"
                    echo "Set GCP_PROJECT_ID=$project_id"
                    echo "export GCP_PROJECT_ID=\"$project_id\"" >> ~/.bashrc
                    ;;
                2)
                    read -p "Enter GCP Region [us-central1]: " region
                    export GCP_REGION="${region:-us-central1}"
                    echo "Set GCP_REGION=$GCP_REGION"
                    ;;
                3)
                    ENV=$(select_environment)
                    if [ -f ".env.$ENV" ]; then
                        ${EDITOR:-nano} ".env.$ENV"
                    else
                        echo -e "${RED}Error: .env.$ENV not found${NC}"
                        echo "Run deployment first to generate it"
                    fi
                    ;;
                4)
                    if [ -f "deploy.config.example" ]; then
                        less deploy.config.example
                    fi
                    ;;
            esac
            read -p "Press Enter to continue..."
            ;;
            
        0)
            echo -e "\n${GREEN}Thank you for using GCP Deployment Manager!${NC}\n"
            exit 0
            ;;
            
        *)
            echo -e "${RED}Invalid choice${NC}"
            sleep 1
            ;;
    esac
    
    clear
    echo -e "${CYAN}GCP Deployment Manager - WildePod${NC}\n"
done

