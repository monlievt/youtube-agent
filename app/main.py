"""
app/main.py
FastAPI application factory.
"""
from contextlib import asynccontextmanager
import secrets

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes import auth, channels, health, queue, evaluations
from app.api.dependencies import CurrentPageUser
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.core.encryption import encrypt
import redis.asyncio as aioredis

settings = get_settings()
setup_logging(settings.log_level)
log = get_logger(__name__)


async def check_rate_limit(ip: str, limit: int = 5, period: int = 60) -> bool:
    """
    Mengecek rate limit di Redis untuk IP tertentu.
    Mengizinkan maksimal `limit` request dalam rentang waktu `period` detik.
    """
    try:
        r = aioredis.from_url(settings.redis_url)
        key = f"rate_limit:login:{ip}"
        current = await r.get(key)
        if current is not None and int(current) >= limit:
            return False

        async with r.pipeline(transaction=True) as pipe:
            await pipe.incr(key)
            if current is None:
                await pipe.expire(key, period)
            await pipe.execute()
        return True
    except Exception as e:
        log.error("rate_limiting_error", error_message=str(e))
        return True  # Fallback: izinkan jika Redis mati



@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup dan shutdown events."""
    log.info(
        "hermes_starting",
        environment=settings.app_env,
        function="lifespan",
    )
    yield
    log.info("hermes_shutting_down", function="lifespan")


app = FastAPI(
    title="Hermes YouTube Automation System",
    description="Sistem otomasi upload YouTube untuk channel musik — dikontrol oleh 1 orang.",
    version="1.0.0",
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url="/redoc" if settings.app_env == "development" else None,
    lifespan=lifespan,
)

# ── Static files & Templates ──────────────────────────────────
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# ── Routers ───────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(channels.router)
app.include_router(queue.router)
app.include_router(evaluations.router)


# ── Login & Auth Routes ────────────────────────────────────────
@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login", include_in_schema=False)
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    ip = request.client.host if request.client else "unknown"
    if not await check_rate_limit(ip):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Terlalu banyak percobaan masuk. Coba lagi nanti."}
        )

    correct_username = secrets.compare_digest(
        username.encode("utf-8"),
        settings.dashboard_username.encode("utf-8"),
    )
    correct_password = secrets.compare_digest(
        password.encode("utf-8"),
        settings.dashboard_password.encode("utf-8"),
    )

    if not (correct_username and correct_password):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Username atau password salah"}
        )

    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key="hermes_session",
        value=encrypt(username),
        httponly=True,
        max_age=86400 * 30,  # 30 hari
        samesite="lax",
    )
    return response


@app.get("/logout", include_in_schema=False)
async def logout_page():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("hermes_session")
    return response


# ── Dashboard Pages (Jinja2 HTML, Protected) ───────────────────
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_home(request: Request, user: CurrentPageUser):
    return templates.TemplateResponse("queue.html", {"request": request})


@app.get("/channels", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_channels(request: Request, user: CurrentPageUser):
    return templates.TemplateResponse("channels.html", {"request": request})


@app.get("/evaluations", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_evaluations(request: Request, user: CurrentPageUser):
    return templates.TemplateResponse("evaluations.html", {"request": request})

