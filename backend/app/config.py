"""Central configuration. Everything tunable comes from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Models documented by Groq as supporting response_format json_schema with strict: true.
STRICT_SCHEMA_MODELS = frozenset({"openai/gpt-oss-120b", "openai/gpt-oss-20b"})


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    groq_api_key: str = field(repr=False, default="")
    groq_model: str = "openai/gpt-oss-120b"
    groq_structured_mode: str = "auto"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_timeout_seconds: float = 60.0
    groq_max_retries: int = 1
    groq_temperature: float = 0.2
    groq_max_completion_tokens: int = 8192

    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = BACKEND_DIR / "data"
    allowed_origins: tuple[str, ...] = ()
    access_token: str = field(repr=False, default="")

    max_upload_bytes: int = 5 * 1024 * 1024
    compile_timeout_seconds: int = 300
    # 0 keeps the server up forever. Otherwise it exits after this many minutes without API traffic
    # (health checks excluded), for hosts where it is started on demand (see scripts/nexus-*.sh).
    idle_shutdown_minutes: int = 0

    @property
    def ai_configured(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def use_strict_schema(self) -> bool:
        mode = self.groq_structured_mode
        if mode == "strict":
            return True
        if mode == "json_object":
            return False
        return self.groq_model in STRICT_SCHEMA_MODELS

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cvforge.sqlite3"


def load_settings(env_file: Path | None = None) -> Settings:
    load_dotenv(env_file or BACKEND_DIR / ".env", override=False)
    data_dir = Path(os.environ.get("CVFORGE_DATA_DIR", "").strip() or "./data").expanduser()
    if not data_dir.is_absolute():
        data_dir = BACKEND_DIR / data_dir
    origins = os.environ.get(
        "CVFORGE_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    )
    mode = os.environ.get("GROQ_STRUCTURED_MODE", "auto").strip().lower()
    return Settings(
        groq_api_key=os.environ.get("GROQ_API_KEY", "").strip(),
        groq_model=os.environ.get("GROQ_MODEL", "").strip() or "openai/gpt-oss-120b",
        groq_structured_mode=mode if mode in {"auto", "strict", "json_object"} else "auto",
        groq_base_url=(os.environ.get("GROQ_BASE_URL", "").strip() or "https://api.groq.com/openai/v1").rstrip("/"),
        groq_timeout_seconds=_float("GROQ_TIMEOUT_SECONDS", 60.0),
        groq_max_retries=max(0, min(_int("GROQ_MAX_RETRIES", 1), 3)),
        groq_temperature=_float("GROQ_TEMPERATURE", 0.2),
        groq_max_completion_tokens=_int("GROQ_MAX_COMPLETION_TOKENS", 8192),
        host=os.environ.get("CVFORGE_HOST", "").strip() or "127.0.0.1",
        port=_int("CVFORGE_PORT", 8000),
        data_dir=data_dir.resolve(),
        allowed_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
        access_token=os.environ.get("CVFORGE_ACCESS_TOKEN", "").strip(),
        max_upload_bytes=max(1, _int("CVFORGE_MAX_UPLOAD_MB", 5)) * 1024 * 1024,
        compile_timeout_seconds=max(10, _int("CVFORGE_COMPILE_TIMEOUT_SECONDS", 300)),
        idle_shutdown_minutes=max(0, _int("CVFORGE_IDLE_SHUTDOWN_MINUTES", 0)),
    )
