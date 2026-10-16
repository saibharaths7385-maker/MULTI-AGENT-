import hashlib
import hmac
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.settings import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    AUTH_SECRET,
    COOKIE_SECURE,
    SESSION_MAX_AGE,
)

COOKIE_NAME = "synapse_session"
router = APIRouter(prefix="/api/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    username: str
    password: str


def configured():
    return bool(ADMIN_USERNAME and ADMIN_PASSWORD and len(AUTH_SECRET) >= 32)


def _signature(username, expires):
    message = f"{username}:{expires}".encode()
    return hmac.new(AUTH_SECRET.encode(), message, hashlib.sha256).hexdigest()


def create_session(username, now=None):
    expires = int((time.time() if now is None else now) + SESSION_MAX_AGE)
    return f"{expires}:{_signature(username, expires)}"


def session_is_valid(token, now=None):
    if not configured() or not token:
        return False
    try:
        expires_text, signature = token.split(":", 1)
        expires = int(expires_text)
    except (ValueError, TypeError):
        return False
    current_time = time.time() if now is None else now
    return (
        expires > current_time
        and hmac.compare_digest(signature, _signature(ADMIN_USERNAME, expires))
    )


def authenticated(request: Request):
    return session_is_valid(request.cookies.get(COOKIE_NAME))


@router.get("/status")
def auth_status(request: Request):
    return {
        "configured": configured(),
        "authenticated": authenticated(request),
        "username": ADMIN_USERNAME if authenticated(request) else None,
    }


@router.post("/login")
def login(payload: LoginRequest):
    if not configured():
        return JSONResponse(
            status_code=503,
            content={"detail": "Set ADMIN_PASSWORD and AUTH_SECRET before enabling login."},
        )
    username_ok = hmac.compare_digest(payload.username.encode(), ADMIN_USERNAME.encode())
    password_ok = hmac.compare_digest(payload.password.encode(), ADMIN_PASSWORD.encode())
    if not (username_ok and password_ok):
        return JSONResponse(status_code=401, content={"detail": "Invalid username or password."})

    response = JSONResponse({"ok": True})
    response.set_cookie(
        COOKIE_NAME,
        create_session(ADMIN_USERNAME),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="strict",
        path="/",
    )
    return response


@router.post("/logout")
def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME, path="/", secure=COOKIE_SECURE, httponly=True, samesite="strict")
    return response


def _unauthorized(request):
    if not configured():
        return JSONResponse(
            status_code=503,
            content={"detail": "Login is not configured. Set ADMIN_PASSWORD and AUTH_SECRET."},
        )
    wants_html = "text/html" in request.headers.get("accept", "")
    if wants_html:
        from fastapi.responses import RedirectResponse

        return RedirectResponse("/login", status_code=303)
    return JSONResponse(status_code=401, content={"detail": "Authentication required."})


async def authentication_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in {
        "/api/auth/status",
        "/api/auth/login",
        "/api/auth/logout",
    }:
        if not authenticated(request):
            return _unauthorized(request)
    return await call_next(request)
