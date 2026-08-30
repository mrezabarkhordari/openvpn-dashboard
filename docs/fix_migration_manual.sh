#!/bin/bash
cd "$(dirname "$0")/.."
# Manual fix for migration 0005 - inserts record directly into django_migrations table
# Run on h3 node: ssh h3, cd /opt/ui-ovpn, then run this script

echo "=== Manually Fixing Migration State ==="

# Check if migration 0005 is already recorded
echo "Step 1: Checking current migration state..."
docker compose exec web sqlite3 /app/data/db.sqlite3 "SELECT * FROM django_migrations WHERE app='ui_ovpn' AND name='0005_add_server_daily_stats';"

echo ""
echo "Step 2: Inserting migration record (if not exists)..."

# Insert migration record directly
docker compose exec web sqlite3 /app/data/db.sqlite3 << 'SQL'
INSERT OR IGNORE INTO django_migrations (app, name, applied)
VALUES ('ui_ovpn', '0005_add_server_daily_stats', datetime('now'));
SQL

echo ""
echo "Step 3: Verifying migration record was inserted..."
docker compose exec web sqlite3 /app/data/db.sqlite3 "SELECT * FROM django_migrations WHERE app='ui_ovpn' ORDER BY id;"

echo ""
echo "Step 4: Checking migration status via Django..."
docker compose exec web python manage.py showmigrations openvpn_dashboard

echo ""
echo "=== Done! Migration should now be marked as applied ==="
echo "You can now restart the container and it should work."

