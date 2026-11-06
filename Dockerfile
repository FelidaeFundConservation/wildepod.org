# --- Stage 1: Compile Assets ---
FROM node:20-slim AS asset-builder
WORKDIR /app
RUN npm install -g sass
COPY ./siteapps/static/scss ./siteapps/static/scss
# Compiles SASS into the local destination
RUN sass --style compressed ./siteapps/static/scss/main.scss:./main.css

# --- Stage 2: Production Python 3.10 Application Container ---
FROM python:3.10-slim
WORKDIR /app

# Install uv securely from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Environment configurations for Python/Django performance
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=config.settings.staging

# Copy dependency layers to leverage Docker cache limits
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy compiled SASS static assets from Stage 1
COPY --from=asset-builder /main.css ./siteapps/static/css/main.css

# Copy remaining code files
COPY . .

# Cloud Run defaults to exposing port 8080
EXPOSE 8080

CMD ["uv", "run", "gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4"]
