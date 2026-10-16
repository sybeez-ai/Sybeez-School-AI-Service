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

## AI Teacher / AI Assistant agent loop

One loop for every portal ("AI Teacher" on the student portal, "AI Assistant" elsewhere):

1. **Observe** - the browser sends the current page; the session mint adds authorised context from Core
   (class, subjects, current lesson, grade band) to the system prompt. The model calls `observe_page`
   to get an accessibility-style outline of the screen (route, headings, every visible control with a
   ref such as `e12`, blocked/irreversible flags). Pictures shown on the Picture tab are streamed to the
   Live session as one downscaled JPEG so follow-up questions are answered from the real image.
2. **Plan** - capture intent, topic and class/subject; decide 1-4 steps. `POST /voice/agent/plan` (Qwen,
   safety-checked, deterministic fallback) returns a lesson outline: what to say, a short chalk label and
   which tab (board, picture, 3d) for each step.
3. **Act** - structured tool calls executed in the browser (`navigate_to_page`, `click_element`,
   `type_in_element`, `select_option`, `scroll_page`, `open_lesson`, `teach_on_board`). `teach_on_board` is
   non-blocking: the hand writes while the voice continues, and it can switch tabs and point at picture parts.
4. **Verify** - every tool result says what changed (new route, headings, control count). On failure the
   model re-observes and retries once differently, then explains plainly.
5. **Answer** - the exact, direct reply first (1-2 sentences), then an example only if useful.

Voice transport is browser <-> Gemini Live with an ephemeral token (`POST /voice/gemini/session`, 15-minute
cap, 6 mints/min). Barge-in is native (Live VAD interrupts; the client flushes audio and pending board beats).
Conversation memory is the Live session itself (sliding-window compression + session resumption).

Guardrails: student-portal paths only for students, no password/security/account controls, no file pickers,
no links off-portal, irreversible actions (submit, delete, pay, finish test, payroll) need `confirmed=true`
after the user says yes. Child-safety checks (`modules/teacher/safety.py`) run on lesson plans and the text
fallback (`POST /voice/agent/text`). Providers: Gemini Live for voice, Qwen for plans and text.

### Teaching assets
`GET /assets/topic?q=&subject=&class_no=` returns curated images (with licence and attribution) and an
optional GLB model for a topic, served from S3 through CloudFront. The catalog is
`apps/ai/src/modules/assets/manifest.json`, built by `scripts/ingest_teaching_assets.py` (Wikimedia Commons,
open licences only, Gemini vision child-safety check, upload to S3) and `scripts/build_glb.py`
(generated primitives). Fallback chain: S3 asset -> `found:false` placeholder (the UI draws a generated
placeholder and the teacher uses the board). Nothing is hot-linked at runtime.
