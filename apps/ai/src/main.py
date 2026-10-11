import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.router import api_router
from src.core.config import get_settings, validate_production_settings
from src.core.database import assert_database_role_enforces_rls, engine
from src.core.exceptions import AppError, error_body
from src.core.health import liveness, readiness
from src.core.logging import redact, setup_logging
from src.core.middleware import SecurityMiddleware
from src.version import APP_NAME, APP_VERSION

logger = logging.getLogger("sybeez.ai")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    validate_production_settings(settings)
    if settings.app_env == "production":
        await assert_database_role_enforces_rls()
        if not settings.active_chat_api_key:
            logger.warning("no LLM API key configured")
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    show_docs = settings.app_env != "production"
    app = FastAPI(
        title=APP_NAME,
        version=APP_VERSION,
        description="Sybeez AI Teacher — owns AI behavior; school truth comes from Core API.",
        lifespan=lifespan,
        docs_url="/docs" if show_docs else None,
        redoc_url="/redoc" if show_docs else None,
        openapi_url="/openapi.json" if show_docs else None,
        root_path=settings.root_path,
    )

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, redact(exc.message)))

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError):
        details = [
            {"loc": list(err.get("loc", [])), "msg": redact(err.get("msg")), "type": err.get("type")}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error", "message": "Invalid request", "details": details}},
        )

    @app.exception_handler(HTTPException)
    async def http_handler(_: Request, exc: HTTPException):
        detail = redact(exc.detail) if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(status_code=exc.status_code, content=error_body("http_error", detail))

    @app.exception_handler(Exception)
    async def unhandled_handler(_: Request, exc: Exception):
        logger.exception("unhandled error")
        return JSONResponse(status_code=500, content=error_body("internal_error", "Internal server error"))

    @app.get("/health")
    async def health():
        return liveness()

    @app.get("/ready")
    async def ready():
        body, status_code = await readiness()
        return JSONResponse(status_code=status_code, content=body)

    app.include_router(api_router, prefix="/api/v1/ai")
    app.add_middleware(SecurityMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


app = create_app()
