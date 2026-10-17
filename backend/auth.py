"""Accounts: open sign-up, sign-in, sessions, and email password reset."""
import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from backend import mailer, settings
from backend.database import q
from backend.settings import AUTH_SECRET, COOKIE_SECURE, RESET_TTL, SESSION_MAX_AGE

COOKIE_NAME = "synapse_session"
router = APIRouter(prefix="/api/auth", tags=["authentication"])

USERNAME = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MIN_PASSWORD = 8
MAX_PASSWORD = 200
PUBLIC_API = {
    "/api/auth/status",
    "/api/auth/register",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/forgot",
    "/api/auth/reset",
    "/api/auth/reset/check",
}


# ---------- passwords ----------

def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        _, n, r, p, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p), dklen=32
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = hash_password("synapse-dummy-password")


def password_problem(password):
    if len(password) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters."
    if len(password) > MAX_PASSWORD:
        return "That password is too long."
    return None


# ---------- sessions ----------

def _fingerprint(pw_hash):
    return hashlib.sha256(pw_hash.encode()).hexdigest()[:16]


def _signature(user_id, expires, pw_hash):
    message = f"{user_id}:{expires}:{_fingerprint(pw_hash)}".encode()
    return hmac.new(AUTH_SECRET.encode(), message, hashlib.sha256).hexdigest()


def create_session(user, now=None):
    expires = int((time.time() if now is None else now) + SESSION_MAX_AGE)
    return f"{user['id']}.{expires}.{_signature(user['id'], expires, user['pw_hash'])}"


def user_from_token(token, now=None):
    """Return the user row for a valid session token, else None.

    The signature covers a fingerprint of the password hash, so changing a
    password signs the account out everywhere.
    """
    if not token:
        return None
    try:
        user_text, expires_text, signature = token.split(".", 2)
        user_id, expires = int(user_text), int(expires_text)
    except (ValueError, TypeError):
        return None
    if expires <= (time.time() if now is None else now):
        return None
    rows = q("select * from users where id=?", (user_id,))
    if not rows:
        return None
    user = rows[0]
    if hmac.compare_digest(signature, _signature(user_id, expires, user["pw_hash"])):
        return user
    return None


def current_user(request: Request):
    cached = getattr(request.state, "user", None)
    if cached is not None:
        return cached
    return user_from_token(request.cookies.get(COOKIE_NAME))


def authenticated(request: Request):
    return current_user(request) is not None


def _start_session(user):
    response = JSONResponse({"ok": True, "username": user["username"]})
    response.set_cookie(
        COOKIE_NAME,
        create_session(user),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return response


# ---------- throttling (in memory, per server process) ----------

_hits = defaultdict(deque)
_lock = threading.Lock()


def throttled(key, limit, window):
    now = time.time()
    with _lock:
        hits = _hits[key]
        while hits and hits[0] <= now - window:
            hits.popleft()
        if len(hits) >= limit:
            return True
        hits.append(now)
        if len(_hits) > 5000:
            for stale in [k for k, v in _hits.items() if not v]:
                _hits.pop(stale, None)
    return False


def client_ip(request: Request):
    return request.client.host if request.client else "unknown"


def too_many():
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many attempts. Wait a few minutes and try again."},
    )


def error(status, message):
    return JSONResponse(status_code=status, content={"detail": message})


# ---------- routes ----------

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


class LoginRequest(BaseModel):
    username: str  # a username or an email address
    password: str


class ForgotRequest(BaseModel):
    email: str


class ResetRequest(BaseModel):
    token: str
    password: str


@router.get("/status")
def auth_status(request: Request):
    user = current_user(request)
    return {
        "authenticated": user is not None,
        "username": user["username"] if user else None,
        "email": user["email"] if user else None,
        "registration_open": True,
        "email_enabled": mailer.email_enabled(),
    }


@router.post("/register")
def register(payload: RegisterRequest, request: Request):
    if throttled(("register", client_ip(request)), 10, 3600):
        return too_many()
    username = payload.username.strip()
    email = payload.email.strip().lower()
    if not USERNAME.fullmatch(username):
        return error(400, "Username must be 3-32 characters: letters, numbers, dot, dash or underscore.")
    if not mailer.EMAIL_PATTERN.fullmatch(email) or len(email) > 254:
        return error(400, "Enter a valid email address.")
    problem = password_problem(payload.password)
    if problem:
        return error(400, problem)
    if q("select 1 from users where username=?", (username,)):
        return error(409, "That username is taken. Try another one.")
    if q("select 1 from users where email=?", (email,)):
        return error(409, "An account with that email already exists. Sign in or reset your password.")
    try:
        q(
            "insert into users(username,email,pw_hash,created) values(?,?,?,?)",
            (username, email, hash_password(payload.password), time.time()),
        )
    except sqlite3.IntegrityError:  # lost a race with another sign-up
        return error(409, "That username or email is already registered.")
    user = q("select * from users where username=?", (username,))[0]
    return _start_session(user)


@router.post("/login")
def login(payload: LoginRequest, request: Request):
    identifier = payload.username.strip().lower()
    if throttled(("login-ip", client_ip(request)), 40, 900) or throttled(("login-id", identifier), 8, 900):
        return too_many()
    rows = q("select * from users where username=? or email=?", (identifier, identifier))
    user = rows[0] if rows else None
    # Always run one hash so timing doesn't reveal whether the account exists.
    ok = verify_password(payload.password, user["pw_hash"] if user else _DUMMY_HASH)
    if not (user and ok):
        return error(401, "Username or password is incorrect.")
    return _start_session(user)


@router.post("/logout")
def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME, path="/", secure=COOKIE_SECURE, httponly=True, samesite="lax")
    return response


def _base_url(request: Request):
    return settings.APP_URL or str(request.base_url).rstrip("/")


@router.post("/forgot")
def forgot(payload: ForgotRequest, request: Request):
    email = payload.email.strip().lower()
    if throttled(("forgot-ip", client_ip(request)), 10, 3600) or throttled(("forgot-id", email), 3, 3600):
        return too_many()
    # The answer is identical whether or not the account exists.
    reply = {"ok": True, "email_enabled": mailer.email_enabled()}
    if not reply["email_enabled"]:
        return reply
    rows = q("select * from users where email=?", (email,))
    if not rows:
        return reply
    user = rows[0]
    token = secrets.token_urlsafe(32)
    q("delete from password_resets where user_id=? or expires<?", (user["id"], time.time()))
    q(
        "insert into password_resets(token_hash,user_id,expires) values(?,?,?)",
        (hashlib.sha256(token.encode()).hexdigest(), user["id"], time.time() + RESET_TTL),
    )
    link = f"{_base_url(request)}/reset-password?token={token}"
    subject, text, body = mailer.reset_email(user["username"], link)
    threading.Thread(target=mailer.send_email, args=(user["email"], subject, text, body), daemon=True).start()
    return reply


def _reset_row(token):
    rows = q(
        "select * from password_resets where token_hash=? and expires>?",
        (hashlib.sha256(token.encode()).hexdigest(), time.time()),
    )
    return rows[0] if rows else None


@router.get("/reset/check")
def reset_check(token: str = ""):
    return {"valid": bool(token) and _reset_row(token) is not None}


@router.post("/reset")
def reset(payload: ResetRequest, request: Request):
    if throttled(("reset-ip", client_ip(request)), 20, 3600):
        return too_many()
    problem = password_problem(payload.password)
    if problem:
        return error(400, problem)
    row = _reset_row(payload.token)
    if not row:
        return error(400, "This reset link has expired or was already used. Ask for a new one.")
    q("update users set pw_hash=? where id=?", (hash_password(payload.password), row["user_id"]))
    q("delete from password_resets where user_id=?", (row["user_id"],))
    return {"ok": True}


# ---------- middleware ----------

async def authentication_middleware(request: Request, call_next):
    path = request.url.path
    request.state.user = user_from_token(request.cookies.get(COOKIE_NAME))
    if path.startswith("/api/") and path not in PUBLIC_API and request.state.user is None:
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse("/login", status_code=303)
        return JSONResponse(status_code=401, content={"detail": "Sign in to continue."})
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response
