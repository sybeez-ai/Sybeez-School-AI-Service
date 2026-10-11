# ECS Fargate image for the Sybeez AI service.
# Secrets are not build arguments. Inject them at runtime as environment
# variables (ECS task definition secrets from Secrets Manager) or set
# AWS_SECRETS_MANAGER_SECRET_ID and let the task role call GetSecretValue.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    APP_ENV=production \
    AI_HOST=0.0.0.0 \
    AI_PORT=8001

WORKDIR /app

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

COPY apps/ai/pyproject.toml apps/ai/alembic.ini ./
COPY apps/ai/src ./src

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
        "fastapi>=0.115.0" \
        "uvicorn[standard]>=0.32.0" \
        "sqlalchemy[asyncio]>=2.0.36" \
        "asyncpg>=0.30.0" \
        "psycopg2-binary>=2.9.10" \
        "alembic>=1.14.0" \
        "pydantic>=2.10.0" \
        "pydantic-settings>=2.6.0" \
        "python-jose[cryptography]>=3.3.0" \
        "httpx>=0.28.0" \
        "pgvector>=0.3.6" \
        "sse-starlette>=2.1.0" \
        "email-validator>=2.2.0" \
        "python-multipart>=0.0.17" \
        "boto3>=1.35.0" \
        "redis>=5.2.0" \
    && chown -R app:app /app

USER app

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('AI_PORT','8001')+'/health', timeout=3)"]

CMD ["python", "-c", "import os, uvicorn; uvicorn.run('src.main:app', host=os.environ.get('AI_HOST', '0.0.0.0'), port=int(os.environ.get('AI_PORT', '8001')), proxy_headers=True, forwarded_allow_ips=os.environ.get('FORWARDED_ALLOW_IPS', '*'), timeout_keep_alive=int(os.environ.get('KEEPALIVE_SECONDS', '5')), workers=int(os.environ.get('WEB_CONCURRENCY', '1')))"]
