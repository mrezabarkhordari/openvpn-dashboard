#!/bin/bash
cd "$(dirname "$0")/.."
# Direct database fix - works even when container won't start
# Run on h3 node: ssh h3, cd /opt/ui-ovpn, then run this script

echo "=== Direct Database Fix for Migration 0005 ==="

DB_FILE="./data/db.sqlite3"

# Check if database file exists
if [ ! -f "$DB_FILE" ]; then
    echo "Error: Database file not found at $DB_FILE"
    echo "Please run this script from /opt/ui-ovpn directory"
    exit 1
fi

echo "Step 1: Checking current migration state..."
sqlite3 "$DB_FILE" "SELECT id, app, name, applied FROM django_migrations WHERE app='ui_ovpn' ORDER BY id;"
sqlite3 "$DB_FILE" "SELECT id, app, name, applied FROM django_migrations WHERE app='openvpn_ui' ORDER BY id;"
sqlite3 "$DB_FILE" "SELECT id, app, name, applied FROM django_migrations WHERE app='openvpn_dashboard' ORDER BY id;"

echo ""
echo "Step 2: Checking if migration 0005 is recorded..."
MIGRATION_EXISTS=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM django_migrations WHERE app='ui_ovpn' AND name='0005_add_server_daily_stats';")

if [ "$MIGRATION_EXISTS" -eq "0" ]; then
    echo "Migration 0005 not found. Inserting..."
    sqlite3 "$DB_FILE" "INSERT INTO django_migrations (app, name, applied) VALUES ('ui_ovpn', '0005_add_server_daily_stats', datetime('now'));"
    echo "Migration record inserted!"
else
    echo "Migration 0005 already exists in database."
fi

echo ""
echo "Step 3: Verifying migration record..."
sqlite3 "$DB_FILE" "SELECT id, app, name, applied FROM django_migrations WHERE app='ui_ovpn' ORDER BY id;"
sqlite3 "$DB_FILE" "SELECT id, app, name, applied FROM django_migrations WHERE app='openvpn_ui' ORDER BY id;"
sqlite3 "$DB_FILE" "SELECT id, app, name, applied FROM django_migrations WHERE app='openvpn_dashboard' ORDER BY id;"

echo ""
echo "Step 4: Verifying tables exist..."
sqlite3 "$DB_FILE" ".tables" | grep -i daily

echo ""
echo "=== Done! Migration 0005 is now marked as applied ==="
echo "You can now start the container: docker compose up -d web"

