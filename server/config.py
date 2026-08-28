"""Typed deployment configuration for the local compatibility servers."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT_DIR / "server" / "config.toml"
DEFAULT_DATA_DIR = ROOT_DIR / "server" / "data"
DEFAULT_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60
DEFAULT_GAME_INIT_CAPTURE = DEFAULT_DATA_DIR / "captures" / "tao-original-20260823-1605-game-frames.json"
DEFAULT_GAMEPLAY_CAPTURE = DEFAULT_DATA_DIR / "captures" / "tao-continuous-20260823-174438-game-frames.json"
DEFAULT_RESOURCE_URL = "/ReleaseGame18/Android/1.2.5"

class ConfigError(ValueError):
    """Raised when a requested configuration cannot be loaded or validated."""


@dataclass(frozen=True)
class HttpSettings:
    host: str
    port: int


@dataclass(frozen=True)
class SdkSettings:
    local_base_url: str
    domain_urls: tuple[str, ...]
    site_url: str | None
    pay_url: str | None
    game_track_url: str | None
    upload_image_url: str | None
    media_url: str | None
    auto_credit_g_points: bool


@dataclass(frozen=True)
class GameSettings:
    tcp_host: str
    tcp_port: int
    advertise_host: str
    server_id: int
    server_name: str
    user_name: str
    user_level: int
    server_type: int
    status: int
    close_register: bool
    is_whitelist: int
    resource_url: str
    resource_env_type: str
    notify_url: str
    fixture_dir: Path
    startup_template: Path | None
    init_capture: Path
    gameplay_capture: Path
    poll_interval: float
    trace: bool


@dataclass(frozen=True)
class StorageSettings:
    database_path: Path
    token_ttl_seconds: int


@dataclass(frozen=True)
class LoggingSettings:
    data_dir: Path
    level: str
    server_log: str
    game_tcp_log: str
    console: bool


@dataclass(frozen=True)
class Settings:
    config_path: Path
    app_title: str
    http: HttpSettings
    sdk: SdkSettings
    game: GameSettings
    storage: StorageSettings
    logging: LoggingSettings


def load_settings(
    config_path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> Settings:
    """Load settings with CLI overrides, TOML, legacy environment, then defaults."""
    env = os.environ if environ is None else environ
    explicit_path = config_path is not None or bool(env.get("SERVER_CONFIG_FILE"))
    selected_path = Path(config_path or env.get("SERVER_CONFIG_FILE") or DEFAULT_CONFIG_PATH)
    if not selected_path.is_absolute():
        selected_path = ROOT_DIR / selected_path
    selected_path = selected_path.resolve()

    document: dict[str, Any] = {}
    if selected_path.exists():
        try:
            with selected_path.open("rb") as handle:
                loaded = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"unable to read TOML configuration {selected_path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ConfigError(f"configuration root must be a table: {selected_path}")
        document = loaded
    elif explicit_path:
        raise ConfigError(f"configuration file does not exist: {selected_path}")

    http = _section(document, "http")
    sdk = _section(document, "sdk")
    game = _section(document, "game")
    storage = _section(document, "storage")
    logging_config = _section(document, "logging")

    http_host = _string(_value(http, "host", "SERVER_HTTP_HOST", "0.0.0.0", env, overrides, "http.host"))
    http_port = _integer(_value(http, "port", "SERVER_HTTP_PORT", 8080, env, overrides, "http.port"), "http.port")

    local_base_url = _string(
        _value(sdk, "local_base_url", "SDK_LOCAL_BASE_URL", "http://127.0.0.1:8080/", env, overrides, "sdk.local_base_url")
    ).strip().rstrip("/")
    if not local_base_url:
        local_base_url = "http://127.0.0.1:8080"
    domain_urls = _url_list(
        _value(sdk, "domain_urls", "SDK_DOMAIN_URLS", [], env, overrides, "sdk.domain_urls")
    )

    sdk_settings = SdkSettings(
        local_base_url=local_base_url,
        domain_urls=domain_urls,
        site_url=_optional_string(_value(sdk, "site_url", "SDK_SITE_URL", None, env, overrides, "sdk.site_url")),
        pay_url=_optional_string(_value(sdk, "pay_url", "SDK_PAY_URL", None, env, overrides, "sdk.pay_url")),
        game_track_url=_optional_string(
            _value(sdk, "game_track_url", "SDK_GAME_TRACK_URL", None, env, overrides, "sdk.game_track_url")
        ),
        upload_image_url=_optional_string(
            _value(sdk, "upload_image_url", "SDK_UPLOAD_IMAGE_URL", None, env, overrides, "sdk.upload_image_url")
        ),
        media_url=_optional_string(_value(sdk, "media_url", "SDK_MEDIA_URL", None, env, overrides, "sdk.media_url")),
        auto_credit_g_points=_boolean(
            _value(sdk, "auto_credit_g_points", "SDK_AUTO_CREDIT_G_POINTS", True, env, overrides, "sdk.auto_credit_g_points"),
            "sdk.auto_credit_g_points",
        ),
    )

    data_dir = _path(
        _value(logging_config, "data_dir", "SERVER_DATA_DIR", DEFAULT_DATA_DIR, env, overrides, "logging.data_dir")
    )
    database_path = _path(
        _value(
            storage,
            "database",
            "SERVER_DATABASE_PATH",
            data_dir / "server.sqlite3",
            env,
            overrides,
            "storage.database",
        )
    )

    game_settings = GameSettings(
        tcp_host=_string(_value(game, "tcp_host", "GAME_TCP_HOST", "0.0.0.0", env, overrides, "game.tcp_host")),
        tcp_port=_integer(_value(game, "tcp_port", "GAME_TCP_PORT", 21001, env, overrides, "game.tcp_port"), "game.tcp_port"),
        advertise_host=_string(
            _value(game, "advertise_host", "GAME_TCP_ADVERTISE_HOST", "127.0.0.1", env, overrides, "game.advertise_host")
        ),
        server_id=_integer(_value(game, "server_id", "GAME_SERVER_ID", 4, env, overrides, "game.server_id"), "game.server_id"),
        server_name=_string(_value(game, "server_name", "GAME_SERVER_NAME", "桃花烂漫", env, overrides, "game.server_name")),
        user_name=_string(_value(game, "user_name", "GAME_SERVER_USER_NAME", "", env, overrides, "game.user_name")),
        user_level=_integer(_value(game, "user_level", "GAME_SERVER_USER_LEVEL", 0, env, overrides, "game.user_level"), "game.user_level"),
        server_type=_integer(_value(game, "server_type", "GAME_SERVER_TYPE", 3, env, overrides, "game.server_type"), "game.server_type"),
        status=_integer(_value(game, "status", "GAME_SERVER_STATUS", 1, env, overrides, "game.status"), "game.status"),
        close_register=_boolean(
            _value(game, "close_register", "GAME_CLOSE_REGISTER", False, env, overrides, "game.close_register"),
            "game.close_register",
        ),
        is_whitelist=_integer(_value(game, "is_whitelist", "GAME_IS_WHITELIST", 0, env, overrides, "game.is_whitelist"), "game.is_whitelist"),
        resource_url=_string(
            _value(game, "resource_url", "GAME_RESOURCE_URL", DEFAULT_RESOURCE_URL, env, overrides, "game.resource_url")
        ).strip().rstrip("/")
        or DEFAULT_RESOURCE_URL,
        resource_env_type=_string(
            _value(game, "resource_env_type", "GAME_RESOURCE_ENV_TYPE", "prod", env, overrides, "game.resource_env_type")
        ),
        notify_url=_string(
            _value(
                game,
                "notify_url",
                "GAME_NOTIFY_URL",
                "http://127.0.0.1:8080/local/notify-disabled",
                env,
                overrides,
                "game.notify_url",
            )
        ),
        fixture_dir=_path(
            _value(game, "fixture_dir", "GAME_FIXTURE_DIR", data_dir / "fixtures", env, overrides, "game.fixture_dir")
        ),
        startup_template=_optional_path(
            _value(game, "startup_template", "GAME_STARTUP_TEMPLATE", None, env, overrides, "game.startup_template")
        ),
        init_capture=_path(
            _value(game, "init_capture", "GAME_INIT_CAPTURE", DEFAULT_GAME_INIT_CAPTURE, env, overrides, "game.init_capture")
        ),
        gameplay_capture=_path(
            _value(game, "gameplay_capture", "GAME_PLAY_CAPTURE", DEFAULT_GAMEPLAY_CAPTURE, env, overrides, "game.gameplay_capture")
        ),
        poll_interval=_number(
            _value(game, "poll_interval", "GAME_EVENT_POLL_INTERVAL", 0.2, env, overrides, "game.poll_interval"),
            "game.poll_interval",
        ),
        trace=_boolean(_value(game, "trace", "GAME_TCP_TRACE", False, env, overrides, "game.trace"), "game.trace"),
    )

    storage_settings = StorageSettings(
        database_path=database_path,
        token_ttl_seconds=_integer(
            _value(
                storage,
                "token_ttl_seconds",
                "SERVER_TOKEN_TTL_SECONDS",
                DEFAULT_TOKEN_TTL_SECONDS,
                env,
                overrides,
                "storage.token_ttl_seconds",
            ),
            "storage.token_ttl_seconds",
        ),
    )

    logging_settings = LoggingSettings(
        data_dir=data_dir,
        level=_string(_value(logging_config, "level", "SERVER_LOG_LEVEL", "INFO", env, overrides, "logging.level")).upper(),
        server_log=_string(_value(logging_config, "server_log", "SERVER_LOG_FILE", "server.log", env, overrides, "logging.server_log")),
        game_tcp_log=_string(
            _value(logging_config, "game_tcp_log", "GAME_TCP_LOG_FILE", "game_tcp.log", env, overrides, "logging.game_tcp_log")
        ),
        console=_boolean(_value(logging_config, "console", "SERVER_LOG_CONSOLE", True, env, overrides, "logging.console"), "logging.console"),
    )

    _validate_port(http_port, "http.port")
    _validate_port(game_settings.tcp_port, "game.tcp_port")
    if storage_settings.token_ttl_seconds <= 0:
        raise ConfigError("storage.token_ttl_seconds must be positive")
    if game_settings.poll_interval < 0.05:
        raise ConfigError("game.poll_interval must be at least 0.05 seconds")
    if not logging_settings.server_log or not logging_settings.game_tcp_log:
        raise ConfigError("logging log file names must not be empty")

    return Settings(
        config_path=selected_path,
        app_title=_string(_value(document, "app_title", "SERVER_APP_TITLE", "APK SDK Local Compatibility Server", env, overrides, "app_title")),
        http=HttpSettings(host=http_host, port=http_port),
        sdk=sdk_settings,
        game=game_settings,
        storage=storage_settings,
        logging=logging_settings,
    )


def _section(document: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = document.get(name, {})
    if not isinstance(value, Mapping):
        raise ConfigError(f"configuration section [{name}] must be a table")
    return value


def _value(
    section: Mapping[str, Any],
    key: str,
    env_name: str | None,
    default: Any,
    env: Mapping[str, str],
    overrides: Mapping[str, Any] | None,
    override_key: str,
) -> Any:
    if overrides and override_key in overrides and overrides[override_key] is not None:
        return overrides[override_key]
    if key in section:
        return section[key]
    if env_name and env_name in env:
        return env[env_name]
    return default


def _string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        raise ConfigError(f"expected string, got {type(value).__name__}")
    return str(value)


def _optional_string(value: Any) -> str | None:
    text = _string(value).strip()
    return text or None


def _integer(value: Any, name: str) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def _number(value: Any, name: str) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be a number") from exc


def _boolean(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = _string(value).strip().lower()
    if normalized in {"1", "true", "yes", "on", "y"}:
        return True
    if normalized in {"0", "false", "no", "off", "n", ""}:
        return False
    raise ConfigError(f"{name} must be a boolean")


def _path(value: Any) -> Path:
    path = Path(_string(value))
    return path if path.is_absolute() else (ROOT_DIR / path).resolve()


def _optional_path(value: Any) -> Path | None:
    text = _string(value).strip()
    if not text:
        return None
    return _path(text)


def _url_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        values = [str(item).strip().rstrip("/") for item in value]
    else:
        values = [item.strip().rstrip("/") for item in _string(value).replace(";", ",").split(",")]
    result: list[str] = []
    for item in values:
        if item and item not in result:
            result.append(item)
    return tuple(result)


def _validate_port(value: int, name: str) -> None:
    if not 1 <= value <= 65535:
        raise ConfigError(f"{name} must be between 1 and 65535")
