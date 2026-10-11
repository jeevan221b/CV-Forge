"""Start the backend: `python -m app` (host/port come from CVFORGE_HOST / CVFORGE_PORT)."""
import logging

import uvicorn

from .config import load_settings
from .main import create_app

if __name__ == "__main__":
    settings = load_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if settings.host not in ("127.0.0.1", "localhost", "::1") and not settings.access_token:
        logging.getLogger("cvforge").warning(
            "Listening on %s without CVFORGE_ACCESS_TOKEN: anyone who can reach this address can read your resumes.",
            settings.host)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")
