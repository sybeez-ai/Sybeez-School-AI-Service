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
POST   /api/v1/ai/teacher/sessions
GET    /api/v1/ai/teacher/sessions
GET    /api/v1/ai/teacher/sessions/{id}
POST   /api/v1/ai/teacher/sessions/{id}/messages
POST   /api/v1/ai/teacher/sessions/{id}/stream
POST   /api/v1/ai/teacher/sessions/{id}/resume
GET    /api/v1/ai/teacher/protocol
WS     /api/v1/ai/teacher/sessions/{id}/live
```

## Quick start

```bash
cp .env.example .env
# COGNITO_* must be the same user pool the Core API trusts.
# Tokens must carry school_id, role, and sub or user_id.
docker compose -f docker-compose.dev.yml up -d postgres redis
cd apps/ai && python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export PYTHONPATH=.
alembic upgrade head
uvicorn src.main:app --reload --port 8001
```

Docs: http://localhost:8001/docs

## Production

- `GET /health` is the process check. `GET /ready` checks Postgres.
- Every other route requires a Cognito access or ID token, or a School backend HS256 session token signed with `JWT_SECRET`. `school_id`, `user_id`, and `role` are taken from that token. The backend puts the user id in `sub` and does not set `iss` or `aud`.
- Calls back to Core still send `X-Internal-Token` (`CORE_INTERNAL_TOKEN`), the same value as the backend `AI_SERVICE_TOKEN`.
- GitHub Actions deploy variables are in [docs/deploy-ai.md](docs/deploy-ai.md).
- Each database transaction runs `set_config('app.school_id', ..., true)` and `set_config('app.user_id', ..., true)` so row level security applies. Apply migration `0002_rls`.
- The database role must not be a superuser and must not have `BYPASSRLS`.
- The Fargate image is `infra/docker/ai.Dockerfile`. Pass secrets as environment variables, or set `AWS_SECRETS_MANAGER_SECRET_ID` and grant the task role `secretsmanager:GetSecretValue`.
- Set `APP_ENV=production`. The process will not start with the dev database password, the dev Core token, or an empty Cognito pool.
