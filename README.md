# Sybeez School AI Service

Standalone FastAPI **AI Teacher** service. Owns AI behavior; Core API owns school truth.

| Port | Service |
|------|---------|
| 8001 | AI API (`apps/ai`) |
| 8000 | Core API (external — `Sybeez-School-Backend`) |

## Ownership

- **Core API**: users, schools, students, classes, teaching records, homework, auth/RBAC
- **AI API**: conversations, messages, AI memory, knowledge chunks, RAG, LLM, practice, evaluation
- **Boundary**: AI fetches authorized learning context via Core internal HTTP — never queries Core school tables directly

## Public AI routes

```
POST   /api/v1/ai/chat
POST   /api/v1/ai/conversations
GET    /api/v1/ai/conversations
GET    /api/v1/ai/conversations/{id}
POST   /api/v1/ai/practice
POST   /api/v1/ai/evaluation
GET    /api/v1/ai/learning/summary
```

## Quick start

```bash
cp .env.example .env
# JWT_SECRET must match Core API
docker compose -f docker-compose.dev.yml up -d postgres redis
cd apps/ai && python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export PYTHONPATH=.
alembic upgrade head
uvicorn src.main:app --reload --port 8001
```

Docs: http://localhost:8001/docs
