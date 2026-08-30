#!/bin/bash
cd "$(dirname "$0")/.."
# Script to fix migration state on production
# Run this on the h3 node: ssh h3, then run this script

echo "=== Fixing Migration State ==="
echo ""
echo "Step 1: Checking current migration status..."
docker compose exec web python manage.py showmigrations openvpn_dashboard

echo ""
echo "Step 2: Checking if tables exist..."
docker compose exec web sqlite3 /app/data/db.sqlite3 ".tables" | grep -i daily

echo ""
echo "Step 3: Fake unapply migration 0005..."
docker compose exec web python manage.py migrate openvpn_dashboard 0004_add_committed_bytes_fields --fake

echo ""
echo "Step 4: Check migration status (should show 0005 as unapplied)..."
docker compose exec web python manage.py showmigrations openvpn_dashboard

echo ""
echo "Step 5: Fake apply migration 0005 (since tables already exist)..."
docker compose exec web python manage.py migrate openvpn_dashboard 0005_add_server_daily_stats --fake

echo ""
echo "Step 6: Verify migration status (should all show as applied)..."
docker compose exec web python manage.py showmigrations openvpn_dashboard

echo ""
echo "Step 7: Verify tables exist..."
docker compose exec web sqlite3 /app/data/db.sqlite3 ".tables" | grep -i daily

echo ""
echo "=== Done! Migration state should now be fixed ==="
echo "You can now restart the container and migrations should pass."

