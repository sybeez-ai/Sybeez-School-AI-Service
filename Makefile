.PHONY: up down api migrate seed test

up:
	docker compose -f docker-compose.dev.yml up -d --build

down:
	docker compose -f docker-compose.dev.yml down

api:
	cd apps/ai && PYTHONPATH=. uvicorn src.main:app --reload --host 0.0.0.0 --port 8001

migrate:
	cd apps/ai && PYTHONPATH=. alembic -c alembic.ini upgrade head

test:
	cd apps/ai && PYTHONPATH=. pytest -q
