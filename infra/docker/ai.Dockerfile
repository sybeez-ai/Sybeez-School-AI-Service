FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir \
    "fastapi>=0.115.0" "uvicorn[standard]>=0.32.0" "sqlalchemy[asyncio]>=2.0.36" \
    "asyncpg>=0.30.0" "psycopg2-binary>=2.9.10" "alembic>=1.14.0" \
    "pydantic>=2.10.0" "pydantic-settings>=2.6.0" "python-jose[cryptography]>=3.3.0" \
    "httpx>=0.28.0" "pgvector>=0.3.6" "sse-starlette>=2.1.0" "email-validator>=2.2.0"
COPY apps/ai /app
ENV PYTHONPATH=/app
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8001"]
