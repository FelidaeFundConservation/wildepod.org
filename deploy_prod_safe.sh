#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-wildepod-339517}"
REGION="${GCP_REGION:-us-west2}"
INSTANCE_NAME="${GCP_DB_INSTANCE:-wildepoddb}"
DATABASE_NAME="${PROD_DATABASE_NAME:-prod}"
SECRET_NAME="${SETTINGS_NAME:-django_settings}"
DB_PORT="${DB_PORT:-5440}"
PROXY_COMMAND="${CLOUD_SQL_PROXY:-cloud-sql-proxy}"
VPC_CONNECTOR_NAME="${VPC_CONNECTOR_NAME:-simple}"
RUN_MIGRATIONS=false
DRY_RUN=false
SKIP_TESTS=false
PROMOTE=true

usage() {
    cat <<'EOF'
Usage: ./deploy_prod_safe.sh [options]

Deploy the current checkout to the production App Engine service using the
existing Cloud SQL instance and Secret Manager settings. This script never
creates databases, users, passwords, secrets, VPC connectors, or workflows.

Options:
  --migrate             Apply pending migrations before deployment
  --dry-run             Validate tools, settings, resources, and DB access only
  --skip-tests          Skip the local test suite
    --no-promote          Deploy without routing traffic to the new version
  --project-id ID       GCP project (default: wildepod-339517)
  --region REGION       Cloud SQL region (default: us-west2)
  --instance NAME       Existing Cloud SQL instance (default: wildepoddb)
  --database NAME       Existing database (default: prod)
  --secret NAME         Existing settings secret (default: django_settings)
    --connector NAME      Existing VPC connector (default: simple)
  --port PORT           Local proxy port (default: 5440)
  --proxy PATH          Cloud SQL Auth Proxy executable
  --help                Show this help
EOF
}

die() {
    echo "ERROR: $*" >&2
    exit 1
}

info() {
    echo "INFO: $*"
}

while (($# > 0)); do
    case "$1" in
        --migrate)
            RUN_MIGRATIONS=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --skip-tests)
            SKIP_TESTS=true
            shift
            ;;
        --no-promote)
            PROMOTE=false
            shift
            ;;
        --project-id|--region|--instance|--database|--secret|--connector|--port|--proxy)
            (($# >= 2)) || die "$1 requires a value"
            case "$1" in
                --project-id) PROJECT_ID="$2" ;;
                --region) REGION="$2" ;;
                --instance) INSTANCE_NAME="$2" ;;
                --database) DATABASE_NAME="$2" ;;
                --secret) SECRET_NAME="$2" ;;
                --connector) VPC_CONNECTOR_NAME="$2" ;;
                --port) DB_PORT="$2" ;;
                --proxy) PROXY_COMMAND="$2" ;;
            esac
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            die "unknown option: $1"
            ;;
    esac
done

BUILD_DIR=""
PROXY_PID=""

cleanup() {
    if [[ -n "$PROXY_PID" ]] && kill -0 "$PROXY_PID" 2>/dev/null; then
        kill "$PROXY_PID" 2>/dev/null || true
        wait "$PROXY_PID" 2>/dev/null || true
    fi
    if [[ -n "$BUILD_DIR" ]]; then
        rm -rf "$BUILD_DIR"
    fi
}

trap cleanup EXIT

check_local_tools() {
    local required_commands=(gcloud uv python3 npm sass nc rsync)
    local command_name
    local missing_commands=()

    for command_name in "${required_commands[@]}"; do
        if ! command -v "$command_name" >/dev/null 2>&1; then
            missing_commands+=("$command_name")
        fi
    done

    if [[ ! -x "$PROXY_COMMAND" && -z "$(command -v "$PROXY_COMMAND" 2>/dev/null || true)" ]]; then
        missing_commands+=("$PROXY_COMMAND")
    fi

    if ((${#missing_commands[@]} > 0)); then
        printf 'ERROR: missing local prerequisites: %s\n' "${missing_commands[*]}" >&2
        exit 1
    fi

    gcloud --version >/dev/null
    uv --version >/dev/null
    python3 --version >/dev/null
    npm --version >/dev/null
    sass --version >/dev/null

    if [[ "$SKIP_TESTS" == false ]]; then
        DJANGO_SETTINGS_MODULE=config.settings.ci DJANGO_CI_MODE=true \
            uv run --no-sync python -m pytest --version >/dev/null \
            || die "pytest is unavailable through the project environment"
    fi
}

check_gcp_access() {
    gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q . \
        || die "no active gcloud account; run gcloud auth login"
    gcloud auth application-default print-access-token >/dev/null \
        || die "Application Default Credentials are unavailable; run gcloud auth application-default login"
    gcloud projects describe "$PROJECT_ID" >/dev/null \
        || die "cannot access GCP project: $PROJECT_ID"
}

check_cloud_resources() {
    local connection_name

    gcloud sql instances describe "$INSTANCE_NAME" --project="$PROJECT_ID" >/dev/null \
        || die "Cloud SQL instance does not exist: $PROJECT_ID:$REGION:$INSTANCE_NAME"

    connection_name=$(gcloud sql instances describe "$INSTANCE_NAME" \
        --project="$PROJECT_ID" --format="value(connectionName)")
    [[ "$connection_name" == "$PROJECT_ID:$REGION:$INSTANCE_NAME" ]] \
        || die "Cloud SQL connection is $connection_name, expected $PROJECT_ID:$REGION:$INSTANCE_NAME"

    gcloud sql databases describe "$DATABASE_NAME" --instance="$INSTANCE_NAME" --project="$PROJECT_ID" >/dev/null \
        || die "database does not exist: $DATABASE_NAME"

    gcloud secrets describe "$SECRET_NAME" --project="$PROJECT_ID" >/dev/null \
        || die "Secret Manager secret does not exist: $SECRET_NAME"

    gcloud app describe --project="$PROJECT_ID" >/dev/null \
        || die "App Engine is not initialized in project: $PROJECT_ID"

    gcloud compute networks vpc-access connectors describe "$VPC_CONNECTOR_NAME" \
        --region="$REGION" --project="$PROJECT_ID" >/dev/null \
        || die "VPC connector does not exist: $VPC_CONNECTOR_NAME in $REGION"
}

check_prod_settings() {
    local settings_keys

    settings_keys=$(gcloud secrets versions access latest --secret="$SECRET_NAME" --project="$PROJECT_ID" \
        | awk -F= '/^(PROD_DATABASE_URL|GOOGLE_CLOUD_PROJECT|DJANGO_SECRET_KEY|GS_BUCKET_NAME_PROD)=/{print $1}')

    for key in PROD_DATABASE_URL GOOGLE_CLOUD_PROJECT DJANGO_SECRET_KEY GS_BUCKET_NAME_PROD; do
        grep -qx "$key" <<<"$settings_keys" || die "$key is missing from Secret Manager secret $SECRET_NAME"
    done

    [[ "$(gcloud secrets versions access latest --secret="$SECRET_NAME" --project="$PROJECT_ID" \
        | awk -F= '/^GOOGLE_CLOUD_PROJECT=/{print $2; exit}')" == "$PROJECT_ID" ]] \
        || die "GOOGLE_CLOUD_PROJECT in $SECRET_NAME does not match $PROJECT_ID"
}

start_proxy() {
    local connection_name="$PROJECT_ID:$REGION:$INSTANCE_NAME"
    local proxy_log

    proxy_log=$(mktemp)
    "$PROXY_COMMAND" --address=127.0.0.1 --port="$DB_PORT" "$connection_name" >"$proxy_log" 2>&1 &
    PROXY_PID=$!

    for _ in {1..30}; do
        if ! kill -0 "$PROXY_PID" 2>/dev/null; then
            cat "$proxy_log" >&2
            rm -f "$proxy_log"
            die "Cloud SQL Auth Proxy exited before opening port $DB_PORT"
        fi
        if nc -z 127.0.0.1 "$DB_PORT"; then
            rm -f "$proxy_log"
            info "Cloud SQL Auth Proxy is listening on 127.0.0.1:$DB_PORT"
            return
        fi
        sleep 1
    done

    cat "$proxy_log" >&2
    rm -f "$proxy_log"
    die "Cloud SQL Auth Proxy did not open port $DB_PORT"
}

check_database_access() {
    local plan_file

    start_proxy
    plan_file=$(mktemp)
    GOOGLE_CLOUD_PROJECT="$PROJECT_ID" SETTINGS_NAME="$SECRET_NAME" \
        USE_CLOUD_SQL_AUTH_PROXY=True uv run --no-sync python manage.py migrate \
        --plan --settings=config.settings.prod >"$plan_file" \
        || {
            cat "$plan_file" >&2
            rm -f "$plan_file"
            die "production database connectivity or settings validation failed"
        }
    info "Production settings loaded and database connection verified"

    if [[ "$DRY_RUN" == false && "$RUN_MIGRATIONS" == false ]] \
        && ! grep -q "No planned migration operations" "$plan_file"; then
        cat "$plan_file"
        rm -f "$plan_file"
        die "pending migrations found; rerun with --migrate"
    fi
    rm -f "$plan_file"
}

build_and_deploy() {
    local connection_name="$PROJECT_ID:$REGION:$INSTANCE_NAME"

    BUILD_DIR=$(mktemp -d)
    rsync -a --exclude=.git --exclude=.venv --exclude=__pycache__ --exclude='.env*' \
        --exclude='.deploy.config' --exclude='*.backup' ./ "$BUILD_DIR/"

    uv export --no-hashes --no-dev -o "$BUILD_DIR/requirements.txt"
    sass --style compressed "$BUILD_DIR/siteapps/static/scss/main.scss:$BUILD_DIR/siteapps/static/css/main.css"

    (
        cd "$BUILD_DIR"
        uv sync --frozen --no-dev
        while IFS= read -r css_file; do
            map_file="${css_file%.css}.map"
            if [[ ! -f "$map_file" ]]; then
                sed -i.bak '/sourceMappingURL=.*\.map/d' "$css_file"
                rm -f "$css_file.bak"
            fi
        done < <(find .venv -type f -name '*.css')
        GOOGLE_CLOUD_PROJECT="$PROJECT_ID" SETTINGS_NAME="$SECRET_NAME" \
            DJANGO_SETTINGS_MODULE=config.settings.prod \
            uv run python manage.py collectstatic --noinput
    )

    printf '\n!staticfiles/\n' >> "$BUILD_DIR/.gcloudignore"

    if grep -qE '^(vpc_access_connector|beta_settings|env_variables):' "$BUILD_DIR/prod.yaml"; then
        die "prod.yaml already contains generated Cloud SQL settings; remove them or update this script"
    fi

    cat >> "$BUILD_DIR/prod.yaml" <<EOF

vpc_access_connector:
    name: projects/$PROJECT_ID/locations/$REGION/connectors/$VPC_CONNECTOR_NAME

beta_settings:
  cloud_sql_instances: $connection_name

env_variables:
  CLOUD_SQL_CONNECTION_NAME: $connection_name
  USE_CLOUD_SQL_AUTH_PROXY: "False"
EOF

    if [[ "$PROMOTE" == true ]]; then
        gcloud app deploy "$BUILD_DIR/prod.yaml" --project="$PROJECT_ID" --quiet --promote
    else
        gcloud app deploy "$BUILD_DIR/prod.yaml" --project="$PROJECT_ID" --quiet --no-promote
    fi
}

info "Validating production deployment prerequisites"
info "Project: $PROJECT_ID, region: $REGION, instance: $INSTANCE_NAME, database: $DATABASE_NAME"
check_local_tools
check_gcp_access
check_cloud_resources
check_prod_settings
check_database_access

if [[ "$DRY_RUN" == true ]]; then
    info "Dry run passed; no migration, build, or deployment was performed"
    exit 0
fi

if [[ "$SKIP_TESTS" == false ]]; then
    DJANGO_SETTINGS_MODULE=config.settings.ci DJANGO_CI_MODE=true \
        uv run python -m pytest
fi

if [[ "$RUN_MIGRATIONS" == true ]]; then
    GOOGLE_CLOUD_PROJECT="$PROJECT_ID" SETTINGS_NAME="$SECRET_NAME" \
        USE_CLOUD_SQL_AUTH_PROXY=True uv run python manage.py migrate \
        --settings=config.settings.prod
fi

build_and_deploy
info "Production deployment completed"