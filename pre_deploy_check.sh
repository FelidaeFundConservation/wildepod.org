#!/bin/bash
################################################################################
# Pre-deployment validation script
# 
# This script performs checks before deploying to GCP:
# - Runs tests
# - Checks code style
# - Validates configuration files
# - Ensures no sensitive data in code
#
# Usage: ./pre_deploy_check.sh [environment]
################################################################################

set -e

ENVIRONMENT="${1:-staging}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Pre-Deployment Validation${NC}"
echo -e "${BLUE}Environment: $ENVIRONMENT${NC}"
echo -e "${BLUE}========================================${NC}"

# Track if any checks fail
CHECKS_FAILED=0

################################################################################
# Check 1: Verify environment file exists
################################################################################
echo -e "\n${BLUE}[1/7]${NC} Checking environment configuration..."
if [ ! -f ".env.${ENVIRONMENT}" ]; then
    echo -e "${YELLOW}WARNING:${NC} .env.${ENVIRONMENT} file not found"
    echo -e "Run deployment script first to generate it"
    CHECKS_FAILED=1
else
    # Check for placeholder values
    if grep -q "DJANGO_SECRET_KEY=$" ".env.${ENVIRONMENT}"; then
        echo -e "${RED}ERROR:${NC} DJANGO_SECRET_KEY not set in .env.${ENVIRONMENT}"
        CHECKS_FAILED=1
    fi
    
    if grep -q "MAILGUN_SMTP_PASSWORD=$" ".env.${ENVIRONMENT}"; then
        echo -e "${YELLOW}WARNING:${NC} MAILGUN_SMTP_PASSWORD not set"
    fi
    
    if [ $CHECKS_FAILED -eq 0 ]; then
        echo -e "${GREEN}✓${NC} Environment file exists and has required variables"
    fi
fi

################################################################################
# Check 2: Verify app.yaml exists
################################################################################
echo -e "\n${BLUE}[2/7]${NC} Checking app.yaml configuration..."
case $ENVIRONMENT in
    staging)
        APP_YAML="staging.yaml"
        ;;
    prod)
        APP_YAML="prod.yaml"
        ;;
    bhutan)
        APP_YAML="bhutan.yaml"
        ;;
esac

if [ ! -f "$APP_YAML" ]; then
    echo -e "${RED}ERROR:${NC} $APP_YAML not found"
    CHECKS_FAILED=1
else
    echo -e "${GREEN}✓${NC} $APP_YAML found"
fi

################################################################################
# Check 3: Run Python tests
################################################################################
echo -e "\n${BLUE}[3/7]${NC} Running tests..."
if command -v pytest &> /dev/null; then
    if pytest --collect-only &> /dev/null; then
        if pytest -v; then
            echo -e "${GREEN}✓${NC} All tests passed"
        else
            echo -e "${RED}ERROR:${NC} Tests failed"
            CHECKS_FAILED=1
        fi
    else
        echo -e "${YELLOW}WARNING:${NC} No tests found"
    fi
else
    echo -e "${YELLOW}WARNING:${NC} pytest not installed, skipping tests"
fi

################################################################################
# Check 4: Check for common security issues
################################################################################
echo -e "\n${BLUE}[4/7]${NC} Checking for security issues..."
SECURITY_ISSUES=0

# Check for hardcoded secrets
if grep -r "SECRET_KEY\s*=\s*['\"].*['\"]" config/settings/*.py 2>/dev/null | grep -v "env("; then
    echo -e "${RED}ERROR:${NC} Hardcoded SECRET_KEY found"
    SECURITY_ISSUES=1
fi

# Check for DEBUG=True in production settings
if [ "$ENVIRONMENT" = "prod" ]; then
    if grep "DEBUG\s*=\s*True" "config/settings/prod.py" 2>/dev/null; then
        echo -e "${RED}ERROR:${NC} DEBUG=True found in production settings"
        SECURITY_ISSUES=1
    fi
fi

# Check for database passwords in code
if grep -r "PASSWORD.*=.*['\"][^'\"]*['\"]" . --include="*.py" 2>/dev/null | \
   grep -v "env(" | grep -v "getpass" | grep -v ".pyc" | grep -v "__pycache__" | grep -v "tests"; then
    echo -e "${YELLOW}WARNING:${NC} Possible hardcoded passwords found"
fi

# Check for AWS/GCP keys
if grep -r "AKIA[0-9A-Z]\{16\}" . 2>/dev/null | grep -v ".git"; then
    echo -e "${RED}ERROR:${NC} AWS access key found in code"
    SECURITY_ISSUES=1
fi

if [ $SECURITY_ISSUES -eq 0 ]; then
    echo -e "${GREEN}✓${NC} No obvious security issues found"
else
    CHECKS_FAILED=1
fi

################################################################################
# Check 5: Validate Python syntax
################################################################################
echo -e "\n${BLUE}[5/7]${NC} Validating Python syntax..."
SYNTAX_ERRORS=0

while IFS= read -r file; do
    if ! python -m py_compile "$file" 2>/dev/null; then
        echo -e "${RED}ERROR:${NC} Syntax error in $file"
        SYNTAX_ERRORS=1
    fi
done < <(find . -name "*.py" -not -path "./venv/*" -not -path "./.venv/*" -not -path "./env/*")

if [ $SYNTAX_ERRORS -eq 0 ]; then
    echo -e "${GREEN}✓${NC} No syntax errors found"
else
    CHECKS_FAILED=1
fi

################################################################################
# Check 6: Check migrations
################################################################################
echo -e "\n${BLUE}[6/7]${NC} Checking for unapplied migrations..."
if python manage.py showmigrations --settings="config.settings.local" 2>/dev/null | grep "\[ \]" > /dev/null; then
    echo -e "${YELLOW}WARNING:${NC} Unapplied migrations detected"
    echo -e "Make sure to run migrations after deployment"
else
    echo -e "${GREEN}✓${NC} No unapplied migrations (local check)"
fi

################################################################################
# Check 7: Check dependencies
################################################################################
echo -e "\n${BLUE}[7/7]${NC} Checking dependencies..."
if [ -f "requirements.txt" ]; then
    # Check if requirements.txt is up to date
    if command -v pip &> /dev/null; then
        # Simple check - just verify file exists and is readable
        echo -e "${GREEN}✓${NC} requirements.txt found"
    fi
else
    echo -e "${RED}ERROR:${NC} requirements.txt not found"
    CHECKS_FAILED=1
fi

################################################################################
# Summary
################################################################################
echo -e "\n${BLUE}========================================${NC}"
if [ $CHECKS_FAILED -eq 0 ]; then
    echo -e "${GREEN}All checks passed!${NC}"
    echo -e "Ready to deploy to ${ENVIRONMENT}"
    echo -e "\nTo deploy, run:"
    echo -e "  ${BLUE}./deploy_gcp.sh $ENVIRONMENT --deploy-only${NC}"
    exit 0
else
    echo -e "${RED}Some checks failed!${NC}"
    echo -e "Please fix the issues above before deploying"
    exit 1
fi

