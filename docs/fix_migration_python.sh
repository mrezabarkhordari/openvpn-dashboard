#!/bin/bash
cd "$(dirname "$0")/.."
# Fix migration using Python in container - most reliable method
# Run on h3 node: ssh h3, cd /opt/ui-ovpn, then run this script

echo "=== Fixing Migration Using Python in Container ==="

# Use Python to insert migration record directly
echo "Step 1: Inserting migration record using Python..."
docker compose run --rm --entrypoint python web -c "
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.db import connection
cursor = connection.cursor()

# Check if migration exists
cursor.execute(\"SELECT COUNT(*) FROM django_migrations WHERE app='ui_ovpn' AND name='0005_add_server_daily_stats'\")
exists = cursor.fetchone()[0]

if exists == 0:
    cursor.execute(\"INSERT INTO django_migrations (app, name, applied) VALUES ('ui_ovpn', '0005_add_server_daily_stats', datetime('now'))\")
    print('Migration record inserted successfully')
else:
    print('Migration record already exists')
    
# Verify (old DBs use app='ui_ovpn'; intermediate may use openvpn_ui; current is openvpn_dashboard)
cursor.execute(\"SELECT id, app, name, applied FROM django_migrations WHERE app='ui_ovpn' ORDER BY id\")
for row in cursor.fetchall():
    print(f'  {row}')
cursor.execute(\"SELECT id, app, name, applied FROM django_migrations WHERE app='openvpn_ui' ORDER BY id\")
for row in cursor.fetchall():
    print(f'  {row}')
cursor.execute(\"SELECT id, app, name, applied FROM django_migrations WHERE app='openvpn_dashboard' ORDER BY id\")
for row in cursor.fetchall():
    print(f'  {row}')
"

echo ""
echo "Step 2: Starting container..."
docker compose up -d web

echo ""
echo "Step 3: Checking container logs..."
sleep 2
docker compose logs web --tail 20

echo ""
echo "=== Done! ==="

