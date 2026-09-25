.PHONY: install dev test migrate worker lint

install:
	pip install -e ".[dev]"

dev:
	cp -n .env.example .env || true
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker:
	celery -A app.workers.celery_app worker --loglevel=info --concurrency=4

test:
	DATABASE_URL="sqlite+aiosqlite:///./test.db" \
	SKIP_AUTH="true" \
	ENVIRONMENT="test" \
	USE_S3="false" \
	UPLOAD_DIR="/tmp/aci-test-uploads" \
	JWT_SECRET_KEY="test-secret-key" \
	pytest tests/ -v --tb=short --cov=app --cov-report=term-missing

test-fast:
	DATABASE_URL="sqlite+aiosqlite:///./test.db" \
	SKIP_AUTH="true" \
	ENVIRONMENT="test" \
	USE_S3="false" \
	UPLOAD_DIR="/tmp/aci-test-uploads" \
	JWT_SECRET_KEY="test-secret-key" \
	pytest tests/ -x -q

migrate:
	alembic upgrade head

migrate-create:
	alembic revision --autogenerate -m "$(name)"

migrate-down:
	alembic downgrade -1

lint:
	ruff check app/ tests/
	ruff format --check app/ tests/

format:
	ruff format app/ tests/

db-create:
	createdb aci || echo "Database already exists"

db-drop:
	dropdb aci

create-sqlite-db:
	DATABASE_URL="sqlite+aiosqlite:///./dev.db" .venv/bin/python scripts/create_db.py

docker-up:
	docker compose up -d postgres redis

docker-down:
	docker compose down
