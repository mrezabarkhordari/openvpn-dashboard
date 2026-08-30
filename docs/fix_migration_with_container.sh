#!/bin/bash
cd "$(dirname "$0")/.."
# Fix migration using container - works without sqlite3 on host
# Run on h3 node: ssh h3, cd /opt/ui-ovpn, then run this script

echo "=== Fixing Migration Using Container ==="

# Option 1: Use a temporary container to run SQL (bypassing entrypoint)
echo "Step 1: Checking migration state using temporary container..."
docker compose run --rm --entrypoint sqlite3 web /app/data/db.sqlite3 "SELECT id, app, name, applied FROM django_migrations WHERE app='ui_ovpn' ORDER BY id;"
docker compose run --rm --entrypoint sqlite3 web /app/data/db.sqlite3 "SELECT id, app, name, applied FROM django_migrations WHERE app='openvpn_ui' ORDER BY id;"
docker compose run --rm --entrypoint sqlite3 web /app/data/db.sqlite3 "SELECT id, app, name, applied FROM django_migrations WHERE app='openvpn_dashboard' ORDER BY id;"

echo ""
echo "Step 2: Inserting migration record..."
docker compose run --rm --entrypoint sqlite3 web /app/data/db.sqlite3 "INSERT OR IGNORE INTO django_migrations (app, name, applied) VALUES ('ui_ovpn', '0005_add_server_daily_stats', datetime('now'));"

echo ""
echo "Step 3: Verifying migration record was inserted..."
docker compose run --rm --entrypoint sqlite3 web /app/data/db.sqlite3 "SELECT id, app, name, applied FROM django_migrations WHERE app='ui_ovpn' ORDER BY id;"
docker compose run --rm --entrypoint sqlite3 web /app/data/db.sqlite3 "SELECT id, app, name, applied FROM django_migrations WHERE app='openvpn_ui' ORDER BY id;"
docker compose run --rm --entrypoint sqlite3 web /app/data/db.sqlite3 "SELECT id, app, name, applied FROM django_migrations WHERE app='openvpn_dashboard' ORDER BY id;"

echo ""
echo "Step 4: Starting container..."
docker compose up -d web

echo ""
echo "=== Done! Container should now start successfully ==="

