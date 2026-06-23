"""Docker HEALTHCHECK probe (used by `docker run` locally; the Cloud Run deployment uses
its own HTTP health checks).

Hits the liveness route of whichever server APP_MODE selected.
"""

import os
import sys
import urllib.request

port = os.environ.get("PORT", "8501")
path = "/health" if os.environ.get("APP_MODE") == "api" else "/_stcore/health"

try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=4) as resp:
        sys.exit(0 if resp.status == 200 else 1)
except Exception:
    sys.exit(1)
