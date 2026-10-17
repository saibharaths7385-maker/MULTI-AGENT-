import os
import sys
import tempfile
from pathlib import Path

# Use a throwaway database and workspace for every test run.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="synapse-test-")
for name in ("RESEND_API_KEY", "BREVO_API_KEY", "SMTP_HOST", "AUTH_SECRET"):
    os.environ.pop(name, None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
