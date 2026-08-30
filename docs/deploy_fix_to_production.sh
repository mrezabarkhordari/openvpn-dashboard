#!/bin/bash
cd "$(dirname "$0")/.."
# Script to deploy the fixed aggregate_daily_stats.py to production server
# Run this from your local machine or on the production server

PROD_DIR="/opt/ui-ovpn"
CONTAINER_NAME="openvpn-dashboard"
SERVICE_NAME="web"

echo "=== Deploying Fix to Production ==="

# Option 1: Copy fixed file directly to running container (quick fix)
echo "Option 1: Copying fixed file to running container..."
docker cp openvpn_dashboard/management/commands/aggregate_daily_stats.py ${CONTAINER_NAME}:/app/openvpn_dashboard/management/commands/aggregate_daily_stats.py

# Option 2: Or update on host and rebuild
# cd $PROD_DIR
# cp openvpn_dashboard/management/commands/aggregate_daily_stats.py openvpn_dashboard/management/commands/
# docker compose build
# docker compose restart

echo "=== Restarting container to apply changes ==="
docker compose restart ${SERVICE_NAME}

echo "=== Testing the fix ==="
docker compose exec ${SERVICE_NAME} python manage.py aggregate_daily_stats --all
