# Production Migration Guide

> **Note:** The Django app is now `openvpn_dashboard`. Database tables keep their original names (`ui_ovpn_*`). Use `showmigrations openvpn_dashboard` / `migrate openvpn_dashboard`. On older databases, `django_migrations` may still have `app='ui_ovpn'` or `app='openvpn_ui'` until `0006_rename_app_label` / `0007_rename_app_label` (or `manage.py migrate`) rewrites those rows.

## Problem
The migration `0005_add_server_daily_stats.py` was incorrectly configured to assume `DailyUsageStats` table already exists. It has been fixed to properly create the table.

## Solution Steps

### Step 1: Check Current Migration Status

On your production server, check which migrations have been applied:

```bash
# Check migration status
docker compose exec web python manage.py showmigrations openvpn_dashboard

# Or check directly in the database
docker compose exec web python manage.py migrate --plan
```

### Step 2: Rebuild Docker Image with Fixed Migration

On your development/build machine:

```bash
# Rebuild the image
docker compose build

# Tag and push to your registry (if using a registry)
# Or copy the fixed code to production server
```

On production server:

```bash
# Pull latest code or copy the fixed migration file
# Then rebuild
docker compose build
```

### Step 3: Handle Migration State (If Needed)

If the migration `0005_add_server_daily_stats` shows as applied but the table doesn't exist, you need to unapply it first:

**Option A: If migration shows as applied but table doesn't exist**

```bash
# Fake unapply the migration (remove from django_migrations table without running SQL)
docker compose exec web python manage.py migrate openvpn_dashboard 0004_add_committed_bytes_fields --fake

# Then apply the fixed migration
docker compose exec web python manage.py migrate
```

**Option B: If migration is NOT yet applied (clean state)**

Simply run:

```bash
docker compose exec web python manage.py migrate
```

### Step 4: Verify Tables Were Created

```bash
# Enter the container
docker compose exec web bash

# Check if tables exist
python manage.py dbshell
.tables
# Should see: ui_ovpn_dailyusagestats and ui_ovpn_serverdailystats
.exit
```

### Step 5: Restart Services (if needed)

```bash
docker compose restart web
```

## Quick Commands Reference

```bash
# Standard deployment workflow
docker compose build                    # Rebuild image with fixed migration
docker compose exec web python manage.py migrate  # Apply migrations
docker compose exec web python manage.py collectstatic --noinput  # Collect static files
docker compose restart                  # Restart services

# Check migration status
docker compose exec web python manage.py showmigrations

# Check if tables exist (SQLite)
docker compose exec web sqlite3 /app/data/db.sqlite3 ".tables" | grep daily

# Backup before migration (recommended)
make backup
# OR
mkdir -p backups
docker compose exec web sqlite3 /app/data/db.sqlite3 ".backup '/app/data/backup.sqlite3'"
docker cp $(docker compose ps -q web):/app/data/backup.sqlite3 ./backups/backup-$(date +%Y%m%d-%H%M%S).sqlite3
```

## Troubleshooting

### Error: "Migration 0005 is applied but table doesn't exist"

This means Django thinks the migration ran, but the table wasn't created. Fix it:

```bash
# 1. Fake unapply the broken migration
docker compose exec web python manage.py migrate openvpn_dashboard 0004_add_committed_bytes_fields --fake

# 2. Apply the fixed migration
docker compose exec web python manage.py migrate
```

### Error: "Table already exists"

If you manually created the table, you need to fake the migration:

```bash
docker compose exec web python manage.py migrate openvpn_dashboard 0005_add_server_daily_stats --fake
```

### Check Migration History in Database

```bash
docker compose exec web python manage.py dbshell
SELECT * FROM django_migrations WHERE app IN ('ui_ovpn', 'openvpn_ui', 'openvpn_dashboard') ORDER BY id;
.exit
```

