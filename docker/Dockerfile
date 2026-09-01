# OpenVPN Dashboard - Docker Image
#
# This container runs the OpenVPN management UI and usage collector.
# It needs access to OpenVPN directories on the host system.
#
# Build: docker build -f docker/Dockerfile -t openvpn-dashboard .
# Run: docker-compose up -d

FROM node:22-alpine AS css
WORKDIR /build
COPY package.json package-lock.json* ./
COPY frontend ./frontend
COPY openvpn_dashboard/templates ./openvpn_dashboard/templates
COPY openvpn_dashboard/static/openvpn_dashboard/js ./openvpn_dashboard/static/openvpn_dashboard/js
RUN npm install && npm run build:css

FROM python:3.11-slim-bookworm

# Labels
LABEL maintainer="OpenVPN Dashboard"
LABEL description="OpenVPN Management UI with Django"
LABEL version="1.0"

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Application defaults
    APP_HOME=/app \
    APP_USER=appuser \
    APP_GROUP=appgroup \
    DJANGO_SETTINGS_MODULE=config.settings

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # For healthcheck and debugging
    curl \
    sqlite3 \
    openssl \
    easy-rsa \
    # For running multiple processes (optional simple deployment)
    supervisor \
    # Cleanup
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create application user and group
# Use a specific UID/GID that can be overridden at runtime
ARG UID=1000
ARG GID=1000
RUN groupadd -g ${GID} ${APP_GROUP} && \
    useradd -u ${UID} -g ${APP_GROUP} -m -s /bin/bash ${APP_USER}

# Create application directories
RUN mkdir -p ${APP_HOME} \
    ${APP_HOME}/data \
    ${APP_HOME}/configs \
    ${APP_HOME}/staticfiles \
    ${APP_HOME}/logs \
    && chown -R ${APP_USER}:${APP_GROUP} ${APP_HOME}

# Set working directory
WORKDIR ${APP_HOME}

# Copy requirements first for better caching
COPY --chown=${APP_USER}:${APP_GROUP} requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=${APP_USER}:${APP_GROUP} . .
COPY --from=css --chown=${APP_USER}:${APP_GROUP} /build/openvpn_dashboard/static/openvpn_dashboard/css/app.css \
    ${APP_HOME}/openvpn_dashboard/static/openvpn_dashboard/css/app.css

# Copy and set up entrypoint script
COPY --chown=${APP_USER}:${APP_GROUP} docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Copy supervisord config for simple deployment
COPY --chown=${APP_USER}:${APP_GROUP} docker/supervisord.conf ${APP_HOME}/supervisord.conf

# Create volume mount points
# These will be mounted from the host
VOLUME ["/app/data", "/app/configs"]

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/login/ || exit 1

# Switch to non-root user for security
# Note: For OpenVPN operations, the container may need to run as root
# or the appuser needs to be in the appropriate groups
USER ${APP_USER}

# Default command
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "config.wsgi:application"]

