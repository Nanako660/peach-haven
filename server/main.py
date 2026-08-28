"""FastAPI entry point for the local APK SDK compatibility server."""

from __future__ import annotations

import hashlib
import argparse
import json
import logging
import secrets
import string
import sys
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .config import ConfigError, Settings, load_settings
from .crypto import ProtocolError, decode_json, decode_request, encode_json
from .products import resolve_game_product, resolve_product
from .storage import Storage


APP_TITLE = "APK SDK Local Compatibility Server"
TOKEN_ERROR_CODE = "2002"
BAD_REQUEST_CODE = "4000"
AUTH_ERROR_CODE = "1001"
PAYMENT_BALANCE_ERROR_CODE = "2003"
PAYMENT_ORDER_ERROR_CODE = "4003"
router = APIRouter()


@dataclass(frozen=True)
class AppContext:
    settings: Settings
    storage: Storage
    logger: logging.Logger


_context_var: ContextVar[AppContext | None] = ContextVar("apk_sdk_app_context", default=None)
_default_context: AppContext | None = None


def _current_context() -> AppContext:
    context = _context_var.get() or _default_context
    if context is None:
        raise RuntimeError("server application context is not initialized")
    return context


class _ContextProxy:
    def __init__(self, attribute: str) -> None:
        self.attribute = attribute

    def __getattr__(self, name: str) -> Any:
        return getattr(getattr(_current_context(), self.attribute), name)


logger = _ContextProxy("logger")
storage = _ContextProxy("storage")


def _configure_logging(settings: Settings, logger_name: str = "apk_sdk_server") -> logging.Logger:
    settings.logging.data_dir.mkdir(parents=True, exist_ok=True)
    configured_level = getattr(logging, settings.logging.level.upper(), logging.INFO)
    service_logger = logging.getLogger(logger_name)
    service_logger.setLevel(configured_level)
    service_logger.propagate = False

    managed_handlers = [handler for handler in service_logger.handlers if getattr(handler, "_apk_sdk_managed", False)]
    expected_file = str(settings.logging.data_dir / settings.logging.server_log)
    has_expected_file = any(getattr(handler, "_apk_sdk_path", "") == expected_file for handler in managed_handlers)
    if not has_expected_file or any(
        isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler)
        for handler in managed_handlers
    ) != settings.logging.console:
        for handler in managed_handlers:
            service_logger.removeHandler(handler)
            handler.close()
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        file_handler = logging.FileHandler(settings.logging.data_dir / settings.logging.server_log, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler._apk_sdk_managed = True
        file_handler._apk_sdk_path = expected_file
        service_logger.addHandler(file_handler)
        if settings.logging.console:
            console_handler = logging.StreamHandler(sys.stderr)
            console_handler.setFormatter(formatter)
            console_handler._apk_sdk_managed = True
            service_logger.addHandler(console_handler)
    return service_logger


def _close_managed_handlers(service_logger: logging.Logger) -> None:
    for handler in list(service_logger.handlers):
        if getattr(handler, "_apk_sdk_managed", False):
            service_logger.removeHandler(handler)
            handler.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an application with an isolated settings, storage, and logger context."""
    global _default_context
    resolved_settings = settings or load_settings()
    logger_name = "apk_sdk_server" if settings is None and _default_context is None else f"apk_sdk_server.custom.{id(resolved_settings)}"
    context = AppContext(
        settings=resolved_settings,
        storage=Storage(
            database_path=resolved_settings.storage.database_path,
            token_ttl_seconds=resolved_settings.storage.token_ttl_seconds,
        ),
        logger=_configure_logging(resolved_settings, logger_name=logger_name),
    )
    application = FastAPI(title=resolved_settings.app_title or APP_TITLE)
    application.state.context = context

    @application.middleware("http")
    async def context_middleware(request: Request, call_next: Any) -> Response:
        token = _context_var.set(request.app.state.context)
        try:
            return await call_next(request)
        finally:
            _context_var.reset(token)

    @application.on_event("startup")
    def startup() -> None:
        context.storage.initialize()
        context.logger.info(
            "server started auto_credit_g_points=%s config=%s",
            context.settings.sdk.auto_credit_g_points,
            context.settings.config_path,
        )

    @application.on_event("shutdown")
    def shutdown() -> None:
        _close_managed_handlers(context.logger)

    application.include_router(router)
    if _default_context is None:
        _default_context = context
    return application


@router.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"status": "ok", "service": "apk-sdk-local", "time": int(time.time())}


@router.post("/server/list")
async def server_list(request: Request) -> JSONResponse:
    """Plain JSON route used by ResAPIService.ServerListUrl."""
    try:
        payload = await request.json()
    except (ValueError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    game = _current_context().settings.game
    server = {
        "server_id": game.server_id,
        "name": game.server_name,
        "addr": game.advertise_host,
        "port": game.tcp_port,
        "user_name": game.user_name,
        "user_level": game.user_level,
        "server_type": game.server_type,
        "status": game.status,
        "close_register": game.close_register,
        "is_whitelist": game.is_whitelist,
    }
    logger.info(
        "server/list accepted platform=%s open_id=%s version=%s device_id=%s",
        payload.get("platform", ""),
        payload.get("open_id", ""),
        payload.get("version", ""),
        payload.get("device_id", ""),
    )
    return JSONResponse({"code": 0, "data": {"my_servers": [server], "recommend_servers": []}})


def _local_domain_urls() -> list[str]:
    """Build local SDK candidates without contacting any upstream domain."""
    sdk = _current_context().settings.sdk
    values = list(sdk.domain_urls)
    if not values:
        values = [sdk.local_base_url]

    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _domain_payload() -> dict[str, Any]:
    domains = _local_domain_urls()
    primary = domains[0] if domains else _current_context().settings.sdk.local_base_url
    return {
        "domain": primary,
        "base_url": primary,
        "api_base_url": primary,
        "server_list_url": primary + "/server/list",
        "domains": domains,
        "sdk_domains": domains,
    }


def _resource_payload(request_data: dict[str, Any]) -> dict[str, Any]:
    """Return the original hot-update resource root without contacting it."""
    resource_type = _str(request_data, "resource_type") or _str(request_data, "resourceType")
    game = _current_context().settings.game
    return {
        "env_type": game.resource_env_type,
        "resource_type": resource_type,
        "url": game.resource_url,
    }


def _is_probably_encrypted(body: bytes, content_type: str) -> bool:
    normalized_type = content_type.lower()
    if "application/json" in normalized_type:
        return False
    if "application/octet-stream" in normalized_type:
        return True
    return bool(body) and not body.lstrip().startswith((b"{", b"["))


@router.post("/api/domain")
async def api_domain(request: Request) -> Response:
    """Return local SDK candidates for domain-probe or relay compatibility calls."""
    body = await request.body()
    encrypted = _is_probably_encrypted(body, request.headers.get("content-type", ""))
    request_object: Any = {}
    token = ""

    if encrypted:
        try:
            request_object = decode_json(body)
            if isinstance(request_object, dict):
                token = str(request_object.get("token") or "")
        except (ProtocolError, ValueError, TypeError) as exc:
            logger.warning(
                "api/domain rejected format=encrypted reason=%s content_length=%s",
                exc,
                len(body),
            )
            return _error(BAD_REQUEST_CODE, "invalid encrypted request")
    elif body:
        try:
            request_object = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "api/domain rejected format=plain reason=%s content_length=%s",
                exc,
                len(body),
            )
            return JSONResponse({"code": BAD_REQUEST_CODE, "data": None})

    payload = _domain_payload()
    logger.info(
        "api/domain accepted format=%s domain_count=%s token_fp=%s request_keys=%s",
        "encrypted" if encrypted else "plain",
        len(payload["domains"]),
        _token_fingerprint(token),
        ",".join(sorted(request_object)) if isinstance(request_object, dict) else "-",
    )
    if encrypted:
        return _encrypted_result(_result(payload))
    return JSONResponse({"code": 0, "data": payload})


@router.post("/resource/url")
async def resource_url(request: Request) -> Response:
    """Return the hot-update root expected by ResAPIService.SendHotfixAsync."""
    body = await request.body()
    encrypted = _is_probably_encrypted(body, request.headers.get("content-type", ""))
    request_object: Any = {}

    if encrypted:
        try:
            request_object = decode_json(body)
        except (ProtocolError, ValueError, TypeError) as exc:
            logger.warning(
                "resource/url rejected format=encrypted reason=%s content_length=%s",
                exc,
                len(body),
            )
            return _error(BAD_REQUEST_CODE, "invalid encrypted request")
        request_data = request_object.get("data") if isinstance(request_object, dict) else {}
    elif body:
        try:
            request_object = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "resource/url rejected format=plain reason=%s content_length=%s",
                exc,
                len(body),
            )
            return JSONResponse({"code": BAD_REQUEST_CODE, "data": None})
        request_data = request_object
    else:
        request_data = {}

    if not isinstance(request_data, dict):
        request_data = {}
    payload = _resource_payload(request_data)
    logger.info(
        "resource/url accepted format=%s resource_type=%s platform=%s version=%s request_keys=%s",
        "encrypted" if encrypted else "plain",
        payload["resource_type"] or "-",
        _str(request_data, "platform") or "-",
        _str(request_data, "version") or "-",
        ",".join(sorted(request_data)) or "-",
    )
    if encrypted:
        return _encrypted_result(_result(payload))
    return JSONResponse({"code": 0, "data": payload})


def _result(data: Any = None, *, status: str = "y", error_code: str = "", error: str = "") -> dict[str, Any]:
    return {
        "status": status,
        "time": str(int(time.time())),
        "errorCode": error_code,
        "error": error,
        "data": data,
    }


def _encrypted_result(result: dict[str, Any]) -> Response:
    return Response(content=encode_json(result), media_type="application/octet-stream")


def _error(error_code: str, message: str) -> Response:
    return _encrypted_result(_result(None, status="n", error_code=error_code, error=message))


async def _request_envelope(request: Request, endpoint: str = "") -> dict[str, Any] | None:
    try:
        return decode_request(await request.body())
    except (ProtocolError, ValueError, TypeError) as exc:
        prefix = endpoint or "request"
        logger.warning("%s rejected errorCode=%s reason=%s", prefix, BAD_REQUEST_CODE, exc)
        return None


def _token_fingerprint(token: str) -> str:
    if not token:
        return "-"
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def _data(envelope: dict[str, Any]) -> dict[str, Any]:
    value = envelope.get("data")
    return value if isinstance(value, dict) else {}


def _str(data: dict[str, Any], key: str, default: str = "") -> str:
    value = data.get(key, default)
    return default if value is None else str(value)


def _login(envelope: dict[str, Any]) -> Response:
    data = _data(envelope)
    username = _str(data, "username").strip()
    password = _str(data, "password")
    if not username or not password:
        return _error(AUTH_ERROR_CODE, "username and password are required")
    row = storage.authenticate(username, password)
    if row is None:
        return _error(AUTH_ERROR_CODE, "invalid username or password")
    token = storage.issue_token(row["id"], envelope.get("deviceId", ""))
    return _encrypted_result(_result(storage.user_data(row, token=token)))


@router.post("/api/sdk/Login/account")
async def login_account(request: Request) -> Response:
    envelope = await _request_envelope(request)
    return _error(BAD_REQUEST_CODE, "invalid encrypted request") if envelope is None else _login(envelope)


@router.post("/api/sdk/Login/username")
async def register_username(request: Request) -> Response:
    envelope = await _request_envelope(request)
    if envelope is None:
        return _error(BAD_REQUEST_CODE, "invalid encrypted request")
    data = _data(envelope)
    username = _str(data, "username").strip()
    password = _str(data, "password")
    if len(username) < 1 or len(password) < 1:
        return _error(AUTH_ERROR_CODE, "username and password are required")
    row = storage.create_user(username, password, _str(data, "channel_code"))
    if row is None:
        return _error(AUTH_ERROR_CODE, "username already exists")
    token = storage.issue_token(row["id"], envelope.get("deviceId", ""))
    return _encrypted_result(_result(storage.user_data(row, token=token)))


@router.post("/api/sdk/Login/quickAccount")
async def quick_account(request: Request) -> Response:
    envelope = await _request_envelope(request)
    if envelope is None:
        return _error(BAD_REQUEST_CODE, "invalid encrypted request")
    data = _data(envelope)
    requested_username = _str(data, "username").strip()
    username = requested_username or "guest_" + secrets.token_hex(4)
    password = _str(data, "password") or "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(12)
    )
    row = storage.create_user(username, password, _str(data, "channel_code"))
    if row is None:
        return _error(AUTH_ERROR_CODE, "unable to create quick account")
    return _encrypted_result(_result({"username": username, "password": password}))


def _session_or_error(envelope: dict[str, Any], endpoint: str = "") -> tuple[Any, str] | Response:
    token = str(envelope.get("token") or "")
    session = storage.get_session(token)
    if session is None:
        if endpoint:
            reason = "missing_token" if not token else "invalid_or_expired_token"
            logger.warning(
                "%s rejected errorCode=%s reason=%s token_present=%s token_fp=%s device_id=%s",
                endpoint,
                TOKEN_ERROR_CODE,
                reason,
                bool(token),
                _token_fingerprint(token),
                envelope.get("deviceId", ""),
            )
        return _error(TOKEN_ERROR_CODE, "invalid or expired token")
    return session


@router.post("/api/sdk/user/validateToken")
async def validate_token(request: Request) -> Response:
    envelope = await _request_envelope(request)
    if envelope is None:
        return _error(BAD_REQUEST_CODE, "invalid encrypted request")
    if storage.get_session(str(envelope.get("token") or "")) is None:
        return _error(TOKEN_ERROR_CODE, "invalid or expired token")
    return _encrypted_result(_result(True))


@router.post("/api/sdk/User/doUpdate")
async def update_profile(request: Request) -> Response:
    envelope = await _request_envelope(request)
    if envelope is None:
        return _error(BAD_REQUEST_CODE, "invalid encrypted request")
    session = _session_or_error(envelope)
    if isinstance(session, Response):
        return session
    updated = storage.update_profile(envelope.get("token", ""), _data(envelope))
    if updated is None:
        return _error(TOKEN_ERROR_CODE, "invalid or expired token")
    return _encrypted_result(_result({}))


@router.post("/api/sdk/system/info")
async def system_info(request: Request) -> Response:
    envelope = await _request_envelope(request)
    if envelope is None:
        return _error(BAD_REQUEST_CODE, "invalid encrypted request")
    session = _session_or_error(envelope)
    if isinstance(session, Response):
        return session
    row, token = session
    sdk = _current_context().settings.sdk
    base_url = sdk.local_base_url
    data = {
        "site_url": sdk.site_url or base_url,
        "pay_url": sdk.pay_url or base_url,
        "game_track_url": sdk.game_track_url or base_url + "/api/sdk/system/gameTrack",
        "upload_image_url": sdk.upload_image_url or base_url + "/api/sdk/upload",
        "media_url": sdk.media_url or base_url,
        "user": storage.user_data(row, token=token),
        "task_points": {
            "daily_invite_charge": 0,
            "newbie_bind_email": 0,
        },
    }
    return _encrypted_result(_result(data))


@router.post("/api/sdk/system/gameTrack")
async def game_track(request: Request) -> Response:
    envelope = await _request_envelope(request, endpoint="system/gameTrack")
    if envelope is None:
        return _error(BAD_REQUEST_CODE, "invalid encrypted request")
    session = _session_or_error(envelope, endpoint="system/gameTrack")
    if isinstance(session, Response):
        return session
    row, _ = session
    data = _data(envelope)
    device_id = str(envelope.get("deviceId") or "")
    event_id = storage.record_game_track(
        row["id"],
        device_id,
        data,
    )
    logger.info(
        "system/gameTrack accepted user_id=%s device_id=%s token_fp=%s data_keys=%s event_id=%s",
        row["id"],
        device_id,
        _token_fingerprint(str(envelope.get("token") or "")),
        ",".join(sorted(data)) or "-",
        event_id,
    )
    return _encrypted_result(_result({}))


async def _mock_payment_success(
    request: Request,
    endpoint: str,
    data: dict[str, Any],
) -> Response:
    """Return an SDK-shaped local payment success without charging or mutating state."""
    envelope = await _request_envelope(request, endpoint=endpoint)
    if envelope is None:
        return _error(BAD_REQUEST_CODE, "invalid encrypted request")
    session = _session_or_error(envelope, endpoint=endpoint)
    if isinstance(session, Response):
        return session
    row, _ = session
    request_data = _data(envelope)
    logger.info(
        "payment endpoint accepted endpoint=%s user_id=%s token_fp=%s data_keys=%s",
        endpoint,
        row["id"],
        _token_fingerprint(str(envelope.get("token") or "")),
        ",".join(sorted(request_data)) or "-",
    )
    return _encrypted_result(_result(data))


@router.post("/api/sdk/UserProduct/getProductList")
async def get_product_list(request: Request) -> Response:
    return await _mock_payment_success(
        request,
        "UserProduct/getProductList",
        {"is_new": [], "product_list": [], "pay_banner": []},
    )


@router.post("/api/sdk/Recharge/create")
async def create_recharge(request: Request) -> Response:
    return await _mock_payment_success(
        request,
        "Recharge/create",
        {"success": True, "msg": "success", "url": ""},
    )


@router.post("/api/sdk/Recharge/createAndSpend")
async def create_recharge_and_spend(request: Request) -> Response:
    return await _mock_payment_success(
        request,
        "Recharge/createAndSpend",
        {"url": ""},
    )


@router.post("/api/sdk/spend/create2")
async def create_spend(request: Request) -> Response:
    envelope = await _request_envelope(request, endpoint="spend/create2")
    if envelope is None:
        return _error(BAD_REQUEST_CODE, "invalid encrypted request")
    session = _session_or_error(envelope, endpoint="spend/create2")
    if isinstance(session, Response):
        return session

    row, _ = session
    request_data = _data(envelope)
    order, duplicate = storage.record_payment_order(
        row["id"],
        str(envelope.get("deviceId") or ""),
        request_data,
    )
    extra: dict[str, Any] = {}
    try:
        parsed_extra = json.loads(order["extra_json"] or "null")
        if isinstance(parsed_extra, dict):
            extra = parsed_extra
    except (TypeError, json.JSONDecodeError):
        extra = {}

    game_order_no = str(extra.get("orderNo") or "")
    game_order = storage.find_game_order_for_payment(
        row["id"],
        order_num=str(order["order_num"] or ""),
        extra_order_no=game_order_no,
    )
    if game_order is not None:
        supplied_order_numbers = {
            value
            for value in (str(order["order_num"] or ""), game_order_no)
            if value
        }
        if supplied_order_numbers != {game_order["game_order_no"]}:
            storage.mark_payment_order_rejected(order["id"], "game order number mismatch")
            logger.warning(
                "game payment rejected reason=order_number_mismatch payment_order_id=%s game_order_id=%s",
                order["id"],
                game_order["id"],
            )
            return _error(PAYMENT_ORDER_ERROR_CODE, "game order number mismatch")
        extra_server_id = str(extra.get("serverId") or "")
        extra_user_id = str(extra.get("userId") or "")
        if extra_server_id and extra_server_id != str(game_order["server_id"]):
            storage.mark_payment_order_rejected(order["id"], "server mismatch")
            return _error(PAYMENT_ORDER_ERROR_CODE, "server mismatch")
        if extra_user_id:
            role = storage.get_game_role(game_order["role_id"])
            if role is None or extra_user_id != str(role["game_uid"]):
                storage.mark_payment_order_rejected(order["id"], "role mismatch")
                return _error(PAYMENT_ORDER_ERROR_CODE, "role mismatch")
        try:
            supplied_amount = int(str(request_data.get("amount") or ""))
        except ValueError:
            supplied_amount = -1
        if supplied_amount != int(game_order["order_price"]):
            storage.mark_payment_order_rejected(order["id"], "amount mismatch")
            return _error(PAYMENT_ORDER_ERROR_CODE, "amount mismatch")
        product = resolve_game_product(game_order["goods_id"], game_order["order_price"])
        if product is None or int(game_order["quantity"]) != 1:
            storage.mark_payment_order_rejected(order["id"], "unknown game product")
            return _error(PAYMENT_ORDER_ERROR_CODE, "unknown game product")
        settlement = storage.settle_game_payment(
            game_order_id=game_order["id"],
            payment_order_id=order["id"],
            product=product,
        )
        if settlement["state"] == "rejected":
            storage.mark_payment_order_rejected(order["id"], settlement.get("reason", "game order rejected"))
            logger.warning(
                "game payment rejected payment_order_id=%s game_order_id=%s reason=%s",
                order["id"],
                game_order["id"],
                settlement.get("reason", "unknown"),
            )
            return _error(PAYMENT_ORDER_ERROR_CODE, settlement.get("reason", "game order rejected"))
        logger.info(
            "game payment settled payment_order_id=%s game_order_id=%s role_id=%s state=%s diamond_after=%s",
            order["id"],
            game_order["id"],
            game_order["role_id"],
            settlement["state"],
            settlement["diamond_after"],
        )
        return _encrypted_result(_result({"extra": ""}))

    # Idempotent retries use the amount persisted with the first request.
    product = resolve_product(order["amount"])
    settlement = None
    if product is not None:
        auto_credit_enabled = _current_context().settings.sdk.auto_credit_g_points
        settlement = storage.settle_payment_order(
            order["id"],
            product,
            auto_credit_g_points=auto_credit_enabled,
        )
        if settlement["state"] == "insufficient_balance":
            logger.warning(
                "payment rejected endpoint=spend/create2 order_id=%s user_id=%s "
                "order_num=%s product_id=%s price=%s balance=%s duplicate=%s "
                "auto_credit_enabled=%s",
                order["id"],
                row["id"],
                order["order_num"] or "-",
                product.product_id,
                product.price,
                settlement["balance_after"],
                duplicate,
                auto_credit_enabled,
            )
            return _error(PAYMENT_BALANCE_ERROR_CODE, "insufficient G points")
    else:
        auto_credit_enabled = _current_context().settings.sdk.auto_credit_g_points
    logger.info(
        "payment order recorded endpoint=spend/create2 order_id=%s user_id=%s "
        "order_num=%s amount=%s status=%s duplicate=%s request_count=%s "
        "notify_url_present=%s token_fp=%s data_keys=%s product_id=%s "
        "settlement=%s balance_after=%s auto_credit_enabled=%s auto_credit_amount=%s",
        order["id"],
        row["id"],
        order["order_num"] or "-",
        order["amount"] or "-",
        order["status"],
        duplicate,
        order["request_count"],
        bool(order["notify_url"]),
        _token_fingerprint(str(envelope.get("token") or "")),
        ",".join(sorted(request_data)) or "-",
        product.product_id if product is not None else "-",
        settlement["state"] if settlement is not None else "unresolved",
        settlement["balance_after"] if settlement is not None else "-",
        auto_credit_enabled,
        settlement["auto_credit_amount"] if settlement is not None else 0,
    )
    return _encrypted_result(_result({"extra": ""}))


@router.post("/api/sdk/login/singleGameVerify")
async def single_game_verify(request: Request) -> Response:
    envelope = await _request_envelope(request)
    if envelope is None:
        return _error(BAD_REQUEST_CODE, "invalid encrypted request")
    session = storage.get_session(str(envelope.get("token") or ""))
    if session is None:
        data = _data(envelope)
        row = storage.authenticate(_str(data, "username"), _str(data, "password"))
        if row is None:
            return _error(TOKEN_ERROR_CODE, "invalid token or credentials")
        token = storage.issue_token(row["id"], envelope.get("deviceId", ""))
    else:
        row, token = session
    return _encrypted_result(_result(storage.user_data(row, token=token, purchased=True)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local APK SDK compatibility server")
    parser.add_argument("--config", help="path to a TOML configuration file")
    parser.add_argument("--host", help="override the configured HTTP bind host")
    parser.add_argument("--port", type=int, help="override the configured HTTP bind port")
    args = parser.parse_args()
    overrides: dict[str, Any] = {}
    if args.host is not None:
        overrides["http.host"] = args.host
    if args.port is not None:
        overrides["http.port"] = args.port
    try:
        settings = load_settings(args.config, overrides=overrides)
    except ConfigError as exc:
        parser.error(str(exc))
    import uvicorn

    application = create_app(settings)
    uvicorn.run(application, host=settings.http.host, port=settings.http.port, reload=False)


if __name__ == "__main__":
    main()
else:
    app = create_app()
