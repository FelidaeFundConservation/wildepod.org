#!/bin/bash

# Local setup script for WildePod Django project
# This script checks for required tools and runs the quick setup commands
# Usage: ./local_setup.sh [--email email@example.com]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse command-line arguments
SUPERUSER_EMAIL=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --email)
            SUPERUSER_EMAIL="$2"
            shift 2
            ;;
        *)
            echo -e "${RED}Error: Unknown argument: $1${NC}"
            echo "Usage: $0 [--email email@example.com]"
            exit 1
            ;;
    esac
done

echo "================================"
echo "WildePod Local Setup Script"
echo "================================"
if [ -n "$SUPERUSER_EMAIL" ]; then
    echo "Superuser email: $SUPERUSER_EMAIL"
fi
echo ""

# Check if running on Ubuntu
if ! grep -qi ubuntu /etc/os-release 2>/dev/null; then
    echo -e "${RED}Error: This script is only supported on Ubuntu${NC}"
    echo ""
    echo "Detected OS:"
    if [ -f /etc/os-release ]; then
        grep "^NAME=" /etc/os-release | cut -d= -f2 | tr -d '"'
    else
        uname -s
    fi
    echo ""
    exit 1
fi

echo -e "${GREEN}✓${NC} Running on Ubuntu"
echo ""

# Track if all checks passed
ALL_CHECKS_PASSED=true

# Function to check if a command exists
check_command() {
    local cmd=$1
    local display_name=$2
    
    if command -v "$cmd" &> /dev/null; then
        echo -e "${GREEN}✓${NC} $display_name is installed"
        return 0
    else
        echo -e "${RED}✗${NC} $display_name is NOT installed"
        ALL_CHECKS_PASSED=false
        return 1
    fi
}

# Function to check if a command exists with version
check_command_with_version() {
    local cmd=$1
    local display_name=$2
    
    if command -v "$cmd" &> /dev/null; then
        local version=$("$cmd" --version 2>&1 | head -n1)
        echo -e "${GREEN}✓${NC} $display_name is installed ($version)"
        return 0
    else
        echo -e "${RED}✗${NC} $display_name is NOT installed"
        ALL_CHECKS_PASSED=false
        return 1
    fi
}

# Function to check if directory exists
check_directory() {
    local dir=$1
    local display_name=$2
    
    if [ -d "$dir" ]; then
        echo -e "${GREEN}✓${NC} $display_name exists"
        return 0
    else
        echo -e "${RED}✗${NC} $display_name does NOT exist"
        ALL_CHECKS_PASSED=false
        return 1
    fi
}

echo "Checking for required tools..."
echo ""

# Check for required tools
check_command_with_version "git" "Git"
check_command_with_version "uv" "UV (Python package manager)"

# Check for Python (can be managed by uv)
if command -v python &> /dev/null; then
    local version=$(python --version 2>&1 | head -n1)
    echo -e "${GREEN}✓${NC} Python is installed ($version)"
elif uv --version &> /dev/null; then
    echo -e "${GREEN}✓${NC} Python is managed by UV (will be installed with uv sync)"
else
    echo -e "${RED}✗${NC} Python is NOT installed"
    ALL_CHECKS_PASSED=false
fi

check_command_with_version "sass" "SASS compiler"

echo ""
echo "Checking for project directory..."
echo ""

# Check if we're in the right directory
if [ -f "manage.py" ] && [ -f "README.md" ]; then
    echo -e "${GREEN}✓${NC} Found WildePod project (manage.py and README.md detected)"
else
    echo -e "${RED}✗${NC} Not in the WildePod project directory"
    echo "  Please run this script from the project root directory"
    exit 1
fi

echo ""
echo "Checking project structure..."
echo ""

check_directory "config" "config directory"
check_directory "siteapps" "siteapps directory"
check_directory "siteapps/templates" "templates directory"
check_directory "scratch" "scratch directory"

echo ""
echo "Checking environment configuration..."
echo ""

# Create .env file if it doesn't exist
if [ -f ".env" ]; then
    echo -e "${GREEN}✓${NC} .env file exists"
else
    echo -e "${YELLOW}→${NC} Creating .env file..."
    # Generate a random SECRET_KEY for local development using Python
    SECRET_KEY=$(python3 -c "import secrets; print(''.join(secrets.choice('abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)') for i in range(50)))")
    
    cat > .env << ENV_EOF
# Local Development Environment Variables
DEBUG=True
DJANGO_DEBUG=True

# Django Secret Key (for local development)
DJANGO_SECRET_KEY=$SECRET_KEY

# Email Configuration (optional, can be set for email testing)
# EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend

# Security (local development - relaxed settings)
DJANGO_SECURE_SSL_REDIRECT=False
DJANGO_SESSION_COOKIE_SECURE=False
DJANGO_CSRF_COOKIE_SECURE=False

# Database (using SQLite locally by default)
# DATABASE_URL=sqlite:///db.sqlite3

# Allow all hosts for local development
# ALLOWED_HOSTS=*

# Add more environment variables as needed for your local setup
ENV_EOF
    echo -e "${GREEN}✓${NC} .env file created with default local settings"
fi

echo ""

if [ "$ALL_CHECKS_PASSED" = false ]; then
    echo -e "${YELLOW}⚠ Warning: Some required tools are missing${NC}"
    echo ""
    echo "Install missing tools:"
    echo "  - UV: curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "  - SASS: brew install sass/sass/sass (or visit https://sass-lang.com/install)"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo ""
echo "================================"
echo "Running Setup Commands"
echo "================================"
echo ""

# Step 1: Install dependencies with uv
echo -e "${YELLOW}→${NC} Installing dependencies with uv sync..."
uv sync
echo -e "${GREEN}✓${NC} Dependencies installed"
echo ""

# Step 2: Make migrations
echo -e "${YELLOW}→${NC} Creating database migrations..."
uv run manage.py makemigrations --settings=config.settings.local
echo -e "${GREEN}✓${NC} Migrations created"
echo ""

# Step 3: Apply migrations
echo -e "${YELLOW}→${NC} Applying migrations to database..."
uv run manage.py migrate --settings=config.settings.local
echo -e "${GREEN}✓${NC} Migrations applied"
echo ""

# Step 4: Create superuser
echo -e "${YELLOW}→${NC} Creating superuser account..."
if [ -n "$SUPERUSER_EMAIL" ]; then
    echo "  Using provided email: $SUPERUSER_EMAIL"
    # Create superuser using Python shell to handle existing users gracefully
    uv run manage.py shell --settings=config.settings.local << EOF
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(email="$SUPERUSER_EMAIL").exists():
    User.objects.create_superuser(email='$SUPERUSER_EMAIL', password='admin123')
    print('✓ Superuser created')
else:
    print('⚠ Superuser with email $SUPERUSER_EMAIL already exists')
EOF
else
    echo "  (You will be prompted to enter superuser credentials)"
    uv run manage.py createsuperuser --settings=config.settings.local
    echo -e "${GREEN}✓${NC} Superuser created"
fi
echo ""

# Final message
echo "================================"
echo -e "${GREEN}Setup Complete!${NC}"
echo "================================"
echo ""
echo "Next steps:"
echo "  1. To run the development server:"
echo "     uv run manage.py runserver --settings=config.settings.local"
echo ""
echo "  2. The server will be available at:"
echo "     http://localhost:8000"
echo ""
echo "  3. Admin interface:"
echo "     http://localhost:8000/admin"
echo ""
