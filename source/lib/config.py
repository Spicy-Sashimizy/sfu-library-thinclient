"""Server configuration from environment variables and Docker secrets."""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

SERVER_VERSION = "1.1.0-phase-g"

logger = logging.getLogger("sfu_library_mcp")


def _int_env(name: str, default: int) -> int:
    """Parse an int env var, falling back to the default on missing/invalid values."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid int for %s=%r; using default %s", name, raw, default)
        return default


def _float_env(name: str, default: float) -> float:
    """Parse a float env var, falling back to the default on missing/invalid values."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid float for %s=%r; using default %s", name, raw, default)
        return default

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SPLADE_MODEL_PATH = str(_REPO_ROOT / "models" / "splade_onnx_fused")
_DEFAULT_EMBED_MODEL_PATH = _REPO_ROOT / "models" / "sfu-academic-embed-v5"


@dataclass
class ServerConfig:
    """Configuration for the Duck Library MCP server.

    Values come from environment variables with hardcoded fallbacks.
    """

    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: float = 60.0

    log_level: str = "INFO"
    log_file: str = ""

    features: dict[str, bool] = field(default_factory=lambda: {
        "rerank_enabled": True,
        "zotero_enabled": True,
        "europe_pmc_enabled": False,
        "rrf_enabled": False,
        "crossencoder_enabled": True,
        "query_log_enabled": False,
        "engagement_log_enabled": False,
        "federated_search_enabled": True,
        "local_rrf_enabled": True,
    })

    embedding_model_path: str = ""

    zotero_api_key: str = ""
    zotero_user_id: str = ""

    openalex_api_key: str = ""
    openalex_mailto: str = ""
    openalex_daily_call_limit: int = 900
    openalex_tracker_path: str = "/tmp/openalex_calls.json"

    unpaywall_email: str = ""

    sfu_db_registry_cache_ttl: int = 86400
    sfu_db_registry_cache_file: str = "/tmp/sfu_databases_cache.json"

    search_backend: str = "thinclient"
    thinclient_index_root: str = ""

    splade_model_path: str = _DEFAULT_SPLADE_MODEL_PATH
    federated_recency_days: int = 30

    query_log_path: str = ""

    metrics_log_path: str = ""

    semantic_scholar_api_key: str = ""

    active_profile: str = "default"


def _read_secret(name: str, env_var: str, default: str = "") -> str:
    """Read a secret from Docker secret file, falling back to env var.

    Priority: /run/secrets/{name} -> os.environ[env_var] -> default
    """
    secret_path = Path(f"/run/secrets/{name}")
    try:
        if secret_path.is_file():
            value = secret_path.read_text().strip()
            if value:
                logger.debug("Loaded secret '%s' from Docker secret file", name)
                return value
    except OSError:
        pass

    env_value = os.environ.get(env_var, "")
    if env_value:
        logger.debug("Loaded secret '%s' from env var %s", name, env_var)
        return env_value

    if default:
        return default

    logger.debug("Secret '%s' not found in Docker secrets or env var %s", name, env_var)
    return ""


def _load_dotenv() -> None:
    """Load .env file from project root if it exists.

    Only sets vars that aren't already in the environment.
    """
    for candidate in [
        Path(__file__).parent.parent.parent / ".env",
        Path.cwd() / ".env",
    ]:
        if candidate.is_file():
            try:
                for line in candidate.read_text().splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    if key and key not in os.environ:
                        os.environ[key] = value
                logger.debug("Loaded .env from %s", candidate)
                return
            except OSError:
                pass


def load_config() -> ServerConfig:
    """Load configuration from Docker secrets and environment variables."""
    _load_dotenv()

    def _bool(val: str) -> bool:
        return val.lower() in ("1", "true", "yes", "on")

    default_features = {
        "rerank_enabled": True,
        "zotero_enabled": True,
        "europe_pmc_enabled": False,
        "rrf_enabled": False,
        "crossencoder_enabled": True,
        "query_log_enabled": False,
        "engagement_log_enabled": False,
        "federated_search_enabled": True,
        "local_rrf_enabled": True,
    }
    for key in default_features:
        env_key = f"SFU_FEATURE_{key.upper()}"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            default_features[key] = _bool(env_val)

    return ServerConfig(
        circuit_breaker_threshold=_int_env("SFU_CB_THRESHOLD", 5),
        circuit_breaker_timeout=_float_env("SFU_CB_TIMEOUT", 60.0),
        log_level=os.environ.get("SFU_LOG_LEVEL", "INFO"),
        log_file=os.environ.get("SFU_LOG_FILE", "/tmp/sfu-library-mcp.log"),
        features=default_features,
        active_profile=os.environ.get("SFU_ACTIVE_PROFILE", "default"),
        zotero_api_key=_read_secret("zotero_api_key", "SFU_ZOTERO_API_KEY"),
        zotero_user_id=_read_secret("zotero_user_id", "SFU_ZOTERO_USER_ID"),
        openalex_api_key=_read_secret("openalex_api_key", "OPENALEX_API_KEY"),
        openalex_mailto=_read_secret("openalex_mailto", "OPENALEX_MAILTO"),
        openalex_daily_call_limit=_int_env("OPENALEX_DAILY_CALL_LIMIT", 900),
        openalex_tracker_path=os.environ.get("OPENALEX_TRACKER_PATH", "/tmp/openalex_calls.json"),
        unpaywall_email=_read_secret("unpaywall_email", "UNPAYWALL_EMAIL"),
        sfu_db_registry_cache_ttl=_int_env("SFU_DB_REGISTRY_CACHE_TTL", 86400),
        sfu_db_registry_cache_file=os.environ.get(
            "SFU_DB_REGISTRY_CACHE_FILE", "/tmp/sfu_databases_cache.json"
        ),
        semantic_scholar_api_key=_read_secret(
            "semantic_scholar_api_key", "SFU_SEMANTIC_SCHOLAR_API_KEY"
        ),
        embedding_model_path=os.environ.get("SFU_EMBEDDING_MODEL_PATH")
        or (str(_DEFAULT_EMBED_MODEL_PATH) if _DEFAULT_EMBED_MODEL_PATH.is_dir() else ""),
        query_log_path=os.environ.get("SFU_QUERY_LOG_PATH", ""),
        metrics_log_path=os.environ.get("SFU_METRICS_LOG_PATH", ""),
        search_backend=os.environ.get("SFU_SEARCH_BACKEND", "thinclient"),
        thinclient_index_root=os.environ.get("SFU_THINCLIENT_INDEX_ROOT", ""),
        splade_model_path=os.environ.get(
            "SFU_SPLADE_MODEL_PATH", _DEFAULT_SPLADE_MODEL_PATH
        ),
        federated_recency_days=_int_env("SFU_FEDERATED_RECENCY_DAYS", 30),
    )


def validate_config(config: ServerConfig) -> list[str]:
    """Validate configuration and return a list of warnings."""
    warnings: list[str] = []

    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if config.log_level.upper() not in valid_levels:
        warnings.append(f"Invalid log_level: {config.log_level}")

    if not config.openalex_api_key and not config.openalex_mailto:
        warnings.append("Neither OPENALEX_API_KEY nor OPENALEX_MAILTO set — OpenAlex limited to 1 req/s")

    if config.openalex_tracker_path.startswith("/tmp"):
        warnings.append(
            "OPENALEX_TRACKER_PATH is in /tmp — the daily call counter will reset on container restart. "
            "Set OPENALEX_TRACKER_PATH to a persistent volume path to preserve budget across restarts."
        )

    if not config.unpaywall_email:
        warnings.append("UNPAYWALL_EMAIL is unset — Unpaywall OA resolution disabled")

    if not config.semantic_scholar_api_key:
        warnings.append("SFU_SEMANTIC_SCHOLAR_API_KEY is empty — S2 requests will be unauthenticated (lower rate limit)")

    if not config.zotero_api_key:
        warnings.append("SFU_ZOTERO_API_KEY is empty — Zotero tools will fail")
    if not config.zotero_user_id:
        warnings.append("SFU_ZOTERO_USER_ID is empty — Zotero tools will fail")

    return warnings
