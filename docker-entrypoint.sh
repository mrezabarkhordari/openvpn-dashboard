#!/bin/bash
set -e

# OpenVPN Dashboard Docker Entrypoint Script
# This script initializes the application before starting the main process

echo "================================================"
echo "OpenVPN Dashboard - Starting..."
echo "================================================"

# Function to wait for a file to exist
wait_for_file() {
    local file=$1
    local timeout=${2:-30}
    local count=0
    
    while [ ! -f "$file" ] && [ $count -lt $timeout ]; do
        echo "Waiting for $file..."
        sleep 1
        count=$((count + 1))
    done
    
    if [ -f "$file" ]; then
        echo "Found: $file"
        return 0
    else
        echo "Warning: $file not found after ${timeout}s"
        return 1
    fi
}

# Print configuration info
echo ""
echo "Configuration:"
echo "  DEBUG: ${DEBUG:-False}"
echo "  DATABASE_PATH: ${DATABASE_PATH:-/app/data/db.sqlite3}"
echo "  OPENVPN_DIR: ${OPENVPN_DIR:-/etc/openvpn}"
echo "  OPENVPN_STATUS_LOG: ${OPENVPN_STATUS_LOG:-/var/log/openvpn/status.log}"
echo "  OPENVPN_SERVER_ADDRESS: ${OPENVPN_SERVER_ADDRESS:-not set}"
echo ""

# Ensure data directory exists and has correct permissions
DATA_DIR="${DATABASE_PATH:-/app/data/db.sqlite3}"
DATA_DIR=$(dirname "$DATA_DIR")
if [ ! -d "$DATA_DIR" ]; then
    echo "Creating data directory: $DATA_DIR"
    mkdir -p "$DATA_DIR"
fi

# Ensure configs directory exists
CONFIGS_DIR="${OPENVPN_CLIENT_CONFIG_DIR:-/app/configs}"
if [ ! -d "$CONFIGS_DIR" ]; then
    echo "Creating configs directory: $CONFIGS_DIR"
    mkdir -p "$CONFIGS_DIR"
fi

# Ensure staticfiles directory exists
STATIC_DIR="${STATIC_ROOT:-/app/staticfiles}"
if [ ! -d "$STATIC_DIR" ]; then
    echo "Creating static directory: $STATIC_DIR"
    mkdir -p "$STATIC_DIR"
fi

# Check OpenVPN availability
OPENVPN_DIR="${OPENVPN_DIR:-/etc/openvpn}"
if [ -d "$OPENVPN_DIR" ]; then
    echo "OpenVPN directory found: $OPENVPN_DIR"
    
    # Check for server.conf
    if [ -f "$OPENVPN_DIR/server.conf" ]; then
        echo "OpenVPN server.conf found"
    else
        echo "Warning: OpenVPN server.conf not found"
    fi
    
    # Check for EasyRSA
    EASY_RSA_DIR="${OPENVPN_EASY_RSA_DIR:-$OPENVPN_DIR/easy-rsa}"
    if [ -d "$EASY_RSA_DIR" ]; then
        echo "EasyRSA directory found: $EASY_RSA_DIR"
    else
        echo "Warning: EasyRSA directory not found"
    fi
else
    echo "Warning: OpenVPN directory not found: $OPENVPN_DIR"
    echo "Some features will be disabled."
fi

# Check status log
STATUS_LOG="${OPENVPN_STATUS_LOG:-/var/log/openvpn/status.log}"
if [ -f "$STATUS_LOG" ]; then
    echo "OpenVPN status log found: $STATUS_LOG"
else
    echo "Warning: OpenVPN status log not found: $STATUS_LOG"
    echo "Usage tracking may not work until OpenVPN starts writing to this file."
fi

echo ""
echo "Running database migrations..."
python manage.py migrate --noinput

echo ""
echo "Collecting static files..."
python manage.py collectstatic --noinput --clear --ignore 'src/*' --ignore 'input.css'

echo ""
echo "Setting up admin user..."
# Create admin superuser if credentials are provided and user doesn't exist
if [ -n "$ADMIN_USERNAME" ] && [ -n "$ADMIN_PASSWORD" ]; then
    python manage.py shell << EOF
from django.contrib.auth import get_user_model
User = get_user_model()
username = '${ADMIN_USERNAME}'
password = '${ADMIN_PASSWORD}'
email = '${ADMIN_EMAIL:-admin@localhost}'

if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username=username, email=email, password=password)
    print(f'Admin user "{username}" created successfully.')
else:
    # Update password if user exists (in case password was changed in env)
    user = User.objects.get(username=username)
    user.set_password(password)
    user.is_staff = True
    user.is_superuser = True
    user.save()
    print(f'Admin user "{username}" already exists. Password updated.')
EOF
else
    echo "Warning: ADMIN_USERNAME or ADMIN_PASSWORD not set. Skipping admin user creation."
    echo "You can create an admin user manually with: docker exec -it openvpn-dashboard python manage.py createsuperuser"
fi

echo ""
echo "================================================"
echo "Initialization complete!"
echo "================================================"
echo ""

# Handle different commands
case "$1" in
    gunicorn)
        echo "Starting Gunicorn server..."
        exec "$@"
        ;;
    
    runserver)
        echo "Starting Django development server..."
        exec python manage.py runserver 0.0.0.0:8000
        ;;
    
    collector)
        echo "Starting Usage Collector..."
        exec python -m openvpn_dashboard.services.usage_collector
        ;;
    
    supervisord)
        echo "Starting Supervisord (web + collector)..."
        exec /usr/bin/supervisord -c /app/supervisord.conf
        ;;
    
    shell)
        echo "Starting Django shell..."
        exec python manage.py shell
        ;;
    
    migrate)
        echo "Running migrations..."
        exec python manage.py migrate
        ;;
    
    createsuperuser)
        echo "Creating superuser..."
        exec python manage.py createsuperuser
        ;;
    
    bash)
        echo "Starting bash shell..."
        exec /bin/bash
        ;;
    
    *)
        # Default: run the provided command
        exec "$@"
        ;;
esac

