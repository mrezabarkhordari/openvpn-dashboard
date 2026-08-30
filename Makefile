# OpenVPN Dashboard - Makefile
#
# Common commands for development and deployment

.PHONY: help build up down logs shell migrate collectstatic clean dev-run

# Default target
help:
	@echo "OpenVPN Dashboard - Available Commands"
	@echo ""
	@echo "Docker Commands:"
	@echo "  make build        - Build Docker images"
	@echo "  make up           - Start all services"
	@echo "  make down         - Stop all services"
	@echo "  make logs         - View logs from all services"
	@echo "  make logs-web     - View logs from web service"
	@echo "  make logs-collector - View logs from collector service"
	@echo "  make shell        - Open shell in web container"
	@echo "  make restart      - Restart all services"
	@echo ""
	@echo "Database Commands:"
	@echo "  make migrate      - Run database migrations"
	@echo "  make makemigrations - Create new migrations"
	@echo "  make createsuperuser - Create Django admin user"
	@echo ""
	@echo "Development Commands:"
	@echo "  make dev-run      - Run development server locally"
	@echo "  make dev-collector - Run usage collector locally"
	@echo "  make collectstatic - Collect static files"
	@echo "  make clean        - Remove build artifacts"
	@echo ""
	@echo "Setup Commands:"
	@echo "  make setup        - Initial setup (copy .env, build, migrate)"
	@echo "  make generate-secret - Generate a new Django secret key"

# =============================================================================
# Docker Commands
# =============================================================================

build:
	docker-compose build

up:
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f

logs-web:
	docker-compose logs -f web

logs-collector:
	docker-compose logs -f collector

shell:
	docker-compose exec web bash

restart:
	docker-compose restart

# =============================================================================
# Database Commands
# =============================================================================

migrate:
	docker-compose exec web python manage.py migrate

makemigrations:
	docker-compose exec web python manage.py makemigrations

createsuperuser:
	docker-compose exec -it web python manage.py createsuperuser

# =============================================================================
# Development Commands
# =============================================================================

dev-run:
	python manage.py runserver 0.0.0.0:8000

dev-collector:
	python -m openvpn_dashboard.services.usage_collector

collectstatic:
	docker-compose exec web python manage.py collectstatic --noinput

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .coverage htmlcov 2>/dev/null || true

# =============================================================================
# Setup Commands
# =============================================================================

setup: check-env build
	@echo "Running initial setup..."
	docker-compose up -d web
	@echo "Waiting for web service to be healthy..."
	@sleep 10
	docker-compose exec web python manage.py migrate
	docker-compose up -d collector
	@echo ""
	@echo "Setup complete! Access the UI at http://localhost:8000"
	@echo ""
	@echo "To create an admin user, run: make createsuperuser"

check-env:
	@if [ ! -f .env ]; then \
		echo "Creating .env file from .env.example..."; \
		cp .env.example .env; \
		echo ""; \
		echo "IMPORTANT: Edit .env file and set:"; \
		echo "  - SECRET_KEY (use 'make generate-secret' to generate)"; \
		echo "  - OPENVPN_SERVER_ADDRESS"; \
		echo ""; \
		exit 1; \
	fi

generate-secret:
	@python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# =============================================================================
# Production Commands
# =============================================================================

prod-up:
	docker-compose -f docker-compose.yml up -d

prod-down:
	docker-compose -f docker-compose.yml down

prod-logs:
	docker-compose -f docker-compose.yml logs -f

# Backup database
backup:
	@mkdir -p backups
	docker-compose exec web sqlite3 /app/data/db.sqlite3 ".backup '/app/data/backup.sqlite3'"
	docker cp $$(docker-compose ps -q web):/app/data/backup.sqlite3 ./backups/backup-$$(date +%Y%m%d-%H%M%S).sqlite3
	@echo "Backup saved to backups/"

# Update and restart
update:
	git pull
	docker-compose build
	docker-compose up -d
	docker-compose exec web python manage.py migrate
	docker-compose exec web python manage.py collectstatic --noinput
	@echo "Update complete!"

