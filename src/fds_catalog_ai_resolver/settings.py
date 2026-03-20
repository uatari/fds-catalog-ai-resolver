from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG_ROOT = PROJECT_ROOT.parent / "mcp-fds-product-catalog"
DEFAULT_RELAY_ENV_SOURCE = PROJECT_ROOT.parent / "mcp-grist-ops-mcp" / ".env"


def _split_args(value: str) -> list[str]:
    return [part for part in value.strip().split() if part]


@dataclass(slots=True)
class Settings:
    openai_api_key: str
    openai_base_url: str | None
    openai_model: str
    sqlite_path: Path
    request_timeout_ms: int
    catalog_mcp_command: str
    catalog_mcp_args: list[str]
    catalog_mcp_cwd: Path
    worker_poll_interval_ms: int
    run_worker: bool
    api_host: str
    api_port: int
    log_level: str


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    if DEFAULT_RELAY_ENV_SOURCE.exists():
        load_dotenv(DEFAULT_RELAY_ENV_SOURCE)
    default_args = [str(DEFAULT_CATALOG_ROOT / "src" / "index.js")]
    configured_args = _split_args(os.getenv("CATALOG_MCP_ARGS", ""))
    sqlite_path = Path(os.getenv("SQLITE_PATH", "./state/jobs.sqlite3"))
    if not sqlite_path.is_absolute():
      sqlite_path = (PROJECT_ROOT / sqlite_path).resolve()
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "").strip() or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip(),
        sqlite_path=sqlite_path,
        request_timeout_ms=int(os.getenv("REQUEST_TIMEOUT_MS", "120000")),
        catalog_mcp_command=os.getenv("CATALOG_MCP_COMMAND", "node").strip(),
        catalog_mcp_args=configured_args or default_args,
        catalog_mcp_cwd=Path(os.getenv("CATALOG_MCP_CWD", str(DEFAULT_CATALOG_ROOT))).resolve(),
        worker_poll_interval_ms=int(os.getenv("WORKER_POLL_INTERVAL_MS", "1200")),
        run_worker=os.getenv("RUN_WORKER", "true").strip().lower() not in {"0", "false", "no"},
        api_host=os.getenv("API_HOST", "0.0.0.0").strip(),
        api_port=int(os.getenv("API_PORT", "8011")),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
    )
