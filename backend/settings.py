import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("DATA_DIR", ROOT / "data"))
WS = DATA / "workspaces"
DB = DATA / "synapse.db"

PROVIDER = os.getenv("LLM_PROVIDER", "openai")
MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
BASE = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
KEY = os.getenv("LLM_API_KEY", "")
SANDBOX = os.getenv("SANDBOX", "process")
IMAGE = os.getenv("SANDBOX_IMAGE", "synapse-sandbox")
MAX_FIX = int(os.getenv("MAX_FIX_ROUNDS", "3"))
NEED_OK = os.getenv("REQUIRE_APPROVAL", "1") == "1"

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
AUTH_SECRET = os.getenv("AUTH_SECRET", "")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"
SESSION_MAX_AGE = 12 * 60 * 60
