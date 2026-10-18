import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("DATA_DIR", ROOT / "data"))
WS = DATA / "workspaces"
DB = DATA / "synapse.db"

PROVIDER = os.getenv("LLM_PROVIDER", "openai")
MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
BASE = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
KEY = os.getenv("LLM_API_KEY", "")
FAST_BUILD = os.getenv("FAST_BUILD", "1" if PROVIDER == "ollama" else "0") == "1"
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "900" if PROVIDER == "ollama" else "240"))
LLM_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "512" if FAST_BUILD else "8192"))
SANDBOX = os.getenv("SANDBOX", "process")
IMAGE = os.getenv("SANDBOX_IMAGE", "synapse-sandbox")
MAX_FIX = int(os.getenv("MAX_FIX_ROUNDS", "1" if FAST_BUILD else "3"))
NEED_OK = os.getenv("REQUIRE_APPROVAL", "1") == "1"
# Each person can run this many projects at the same time (protects the shared model key).
MAX_ACTIVE_PER_USER = int(os.getenv("MAX_ACTIVE_PER_USER", "2"))


def _auth_secret():
    """Use AUTH_SECRET when set; otherwise create one once and keep it in the data folder."""
    value = os.getenv("AUTH_SECRET", "")
    if len(value) >= 32:
        return value
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / ".auth_secret"
    if path.exists() and len(path.read_text().strip()) >= 32:
        return path.read_text().strip()
    generated = secrets.token_urlsafe(48)
    path.write_text(generated)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return generated


AUTH_SECRET = _auth_secret()
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"
SESSION_MAX_AGE = 14 * 24 * 60 * 60
RESET_TTL = 60 * 60  # password reset links last one hour

# Public address used inside reset emails. Render provides RENDER_EXTERNAL_URL automatically.
APP_URL = (os.getenv("APP_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")

# Email delivery. Configure ONE of: RESEND_API_KEY, BREVO_API_KEY, or SMTP_HOST.
MAIL_FROM = os.getenv("MAIL_FROM", "")  # e.g. Synapse <you@example.com>
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
